"""Tests for the historical market-data synchronization service."""

from datetime import datetime, timedelta, timezone

import pytest

from src.market_data import Candle
from src.market_feed import CandleRequest, MarketDataError, ProviderUnavailable
from src.historical_data import HistoricalDataService
from src.market_storage import CandleStorage


BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)
NOW = BASE + timedelta(hours=3)


def make_candle(index=0, close=1.1, pair="EUR/USD"):
    stamp = BASE + timedelta(minutes=15 * index)
    return Candle(
        pair, stamp, close, close + 0.001, close - 0.001, close, 100.0
    )


class FakeProvider:
    name = "test-provider"

    def __init__(self, candles=None, error=None):
        self.candles = list(candles or [make_candle(0)])
        self.error = error
        self.calls = 0
        self.last_request = None

    def fetch_candles(self, request):
        self.calls += 1
        self.last_request = request
        if self.error:
            raise self.error
        return self.candles


def make_service(tmp_path, candles=None, error=None):
    provider = FakeProvider(candles, error)
    storage = CandleStorage(tmp_path / "history.db")
    return HistoricalDataService(provider, storage), provider, storage


def test_sync_saves_closed_candles_and_returns_quality(tmp_path):
    values = [make_candle(0), make_candle(1), make_candle(2)]
    service, provider, storage = make_service(tmp_path, values)
    result = service.sync(CandleRequest("EUR/USD", "15m", 10), NOW)
    assert result.fetched_count == 3
    assert result.accepted_count == 3
    assert result.stored_count == 3
    assert result.quality.coverage == 1.0
    assert storage.load_candles("EUR/USD", timeframe="15m") == values
    assert provider.calls == 1


def test_sync_excludes_forming_candle(tmp_path):
    values = [make_candle(0), make_candle(1), make_candle(2)]
    service, _, storage = make_service(tmp_path, values)
    now = BASE + timedelta(minutes=37)
    result = service.sync(CandleRequest("EUR/USD", "15m", 10), now)
    assert result.accepted_count == 2
    assert storage.load_candles("EUR/USD", timeframe="15m") == values[:2]


def test_sync_rejects_forming_only_response_without_writing(tmp_path):
    service, _, storage = make_service(tmp_path, [make_candle(10)])
    with pytest.raises(ValueError, match="fully closed"):
        service.sync(
            CandleRequest("EUR/USD", "15m"),
            BASE + timedelta(hours=2),
        )
    assert storage.load_candles("EUR/USD", timeframe="15m") == []


def test_sync_preserves_existing_history_when_refreshing_recent_window(tmp_path):
    old = [make_candle(i) for i in range(4)]
    recent = [make_candle(2), make_candle(3), make_candle(4)]
    service, _, storage = make_service(tmp_path, recent)
    storage.save_candles(old)
    result = service.sync(CandleRequest("EUR/USD", "15m", 10), NOW)
    assert result.stored_count == 5
    assert storage.load_candles("EUR/USD", timeframe="15m") == [
        *old, make_candle(4)
    ]
    assert storage.load_candles("EUR/USD", timeframe="unknown") == []


def test_sync_provider_correction_replaces_existing_candle(tmp_path):
    original = make_candle(0)
    corrected = make_candle(0, close=1.2)
    service, _, storage = make_service(tmp_path, [corrected])
    storage.save_candles([original])
    service.sync(CandleRequest("EUR/USD", "15m"), NOW)
    assert storage.load_candles("EUR/USD", timeframe="15m") == [corrected]


def test_sync_does_not_duplicate_repeated_candles(tmp_path):
    values = [make_candle(0), make_candle(1)]
    service, _, storage = make_service(tmp_path, values)
    request = CandleRequest("EUR/USD", "15m", 10)
    service.sync(request, NOW)
    service.sync(request, NOW)
    assert storage.load_candles("EUR/USD", timeframe="15m") == values


def test_sync_reports_gaps_without_fabricating_candles(tmp_path):
    values = [make_candle(0), make_candle(3)]
    service, _, storage = make_service(tmp_path, values)
    result = service.sync(CandleRequest("EUR/USD", "15m", 10), NOW)
    assert result.quality.missing == 2
    assert len(result.quality.gaps) == 2
    assert len(storage.load_candles("EUR/USD", timeframe="15m")) == 2


def test_sync_rejects_wrong_pair_from_provider(tmp_path):
    service, _, storage = make_service(
        tmp_path, [make_candle(0, pair="GBP/USD")]
    )
    with pytest.raises(MarketDataError, match="wrong pair"):
        service.sync(CandleRequest("EUR/USD", "15m"), NOW)
    assert storage.load_candles("EUR/USD", timeframe="15m") == []


def test_sync_wraps_provider_outage_and_preserves_history(tmp_path):
    service, provider, storage = make_service(tmp_path, [make_candle(0)])
    storage.save_candles([make_candle(0)], timeframe="15m")
    provider.error = OSError("network unavailable")
    with pytest.raises(ProviderUnavailable):
        service.sync(CandleRequest("EUR/USD", "15m"), NOW)
    assert storage.load_candles("EUR/USD", timeframe="15m") == [make_candle(0)]


def test_sync_passes_request_to_provider(tmp_path):
    service, provider, _ = make_service(tmp_path, [make_candle(0)])
    request = CandleRequest("EUR/USD", "15m", 25)
    service.sync(request, NOW)
    assert provider.last_request is request


def test_load_history_supports_time_range(tmp_path):
    values = [make_candle(i) for i in range(3)]
    service, _, storage = make_service(tmp_path, [make_candle(2)])
    storage.save_candles(values, timeframe="15m")
    result = service.load_history(
        "EUR/USD",
        start=values[1].timestamp,
        end=values[2].timestamp,
        timeframe="15m",
    )
    assert result == values[1:]


def test_sync_rejects_naive_clock_without_writing(tmp_path):
    service, _, storage = make_service(tmp_path, [make_candle(0)])
    with pytest.raises(ValueError, match="timezone"):
        service.sync(
            CandleRequest("EUR/USD", "15m"),
            datetime(2026, 1, 1),
        )
    assert storage.load_candles("EUR/USD", timeframe="15m") == []


def test_sync_keeps_pair_histories_separate(tmp_path):
    service, _, storage = make_service(tmp_path, [make_candle(0)])
    storage.save_candles([make_candle(0, pair="GBP/USD")], timeframe="15m")
    service.sync(CandleRequest("EUR/USD", "15m"), NOW)
    assert len(storage.load_candles("EUR/USD", timeframe="15m")) == 1
    assert len(storage.load_candles("GBP/USD", timeframe="15m")) == 1


def test_sync_result_uses_latest_chronological_timestamp(tmp_path):
    values = [make_candle(0), make_candle(1), make_candle(2)]
    service, _, _ = make_service(tmp_path, values)
    result = service.sync(CandleRequest("EUR/USD", "15m"), NOW)
    assert result.latest_timestamp == values[-1].timestamp


def test_sync_keeps_two_timeframes_isolated(tmp_path):
    fifteen_minute = make_candle(0, close=1.1)
    hourly = Candle(
        "EUR/USD", BASE, 1.0, 1.3, 0.8, 1.2, 500.0
    )
    service, provider, storage = make_service(tmp_path, [fifteen_minute])
    service.sync(CandleRequest("EUR/USD", "15m"), NOW)
    provider.candles = [hourly]
    service.sync(CandleRequest("EUR/USD", "1h"), NOW)
    assert storage.load_candles("EUR/USD", timeframe="15m") == [
        fifteen_minute
    ]
    assert storage.load_candles("EUR/USD", timeframe="1h") == [hourly]


def test_first_sync_migrates_legacy_unknown_partition(tmp_path):
    legacy = [make_candle(0), make_candle(1)]
    service, _, storage = make_service(tmp_path, [make_candle(2)])
    storage.save_candles(legacy)
    service.sync(CandleRequest("EUR/USD", "15m"), NOW)
    assert storage.load_candles("EUR/USD", timeframe="15m") == legacy + [
        make_candle(2)
    ]
    assert storage.load_candles("EUR/USD", timeframe="unknown") == []


def test_load_history_can_select_timeframe(tmp_path):
    fifteen = make_candle(0)
    hourly = Candle("EUR/USD", BASE, 1.0, 1.3, 0.8, 1.2, 500.0)
    service, _, storage = make_service(tmp_path, [fifteen])
    storage.save_candles([fifteen], timeframe="15m")
    storage.save_candles([hourly], timeframe="1h")
    assert service.load_history("EUR/USD", timeframe="1h") == [hourly]


class WindowProvider:
    name = "window-provider"

    def __init__(self, fail_on_call=None):
        self.calls = []
        self.fail_on_call = fail_on_call

    def fetch_candles(self, request):
        self.calls.append(request)
        if self.fail_on_call == len(self.calls):
            raise OSError("temporary provider outage")
        return [
            make_candle(index)
            for index in range(4)
            if request.start <= make_candle(index).timestamp <= request.end
        ]


def test_backfill_splits_large_range_into_bounded_non_overlapping_windows(tmp_path):
    provider = WindowProvider()
    storage = CandleStorage(tmp_path / "backfill.db")
    service = HistoricalDataService(provider, storage)
    result = service.backfill(
        "EUR/USD", "15m", BASE, BASE + timedelta(minutes=45),
        now=NOW, max_candles=2,
    )
    assert result.request_count == 2
    assert result.fetched_count == 4
    assert result.accepted_count == 4
    assert result.stored_count == 4
    assert [request.start for request in provider.calls] == [
        BASE, BASE + timedelta(minutes=30)
    ]
    assert [request.end for request in provider.calls] == [
        BASE + timedelta(minutes=15), BASE + timedelta(minutes=45)
    ]
    assert all(request.limit == 2 for request in provider.calls)
    assert storage.load_candles("EUR/USD", timeframe="15m") == [
        make_candle(index) for index in range(4)
    ]


def test_backfill_single_window_uses_one_provider_request(tmp_path):
    provider = WindowProvider()
    service = HistoricalDataService(
        provider, CandleStorage(tmp_path / "single.db")
    )
    result = service.backfill(
        "EUR/USD", "15m", BASE, BASE + timedelta(minutes=15),
        now=NOW, max_candles=10,
    )
    assert result.request_count == 1
    assert len(provider.calls) == 1


@pytest.mark.parametrize(
    "start,end",
    [
        (datetime(2026, 1, 1), BASE + timedelta(hours=1)),
        (BASE, datetime(2026, 1, 1, 1)),
        (BASE, BASE),
        (BASE + timedelta(hours=1), BASE),
    ],
)
def test_backfill_rejects_invalid_date_ranges(tmp_path, start, end):
    service, provider, _ = make_service(tmp_path, [make_candle(0)])
    with pytest.raises(ValueError):
        service.backfill("EUR/USD", "15m", start, end, now=NOW)
    assert provider.calls == 0


@pytest.mark.parametrize("max_candles", [0, 1, -1, 5001, True, 1.5])
def test_backfill_rejects_invalid_chunk_sizes(tmp_path, max_candles):
    service, provider, _ = make_service(tmp_path, [make_candle(0)])
    with pytest.raises(ValueError, match="between 2 and 5000"):
        service.backfill(
            "EUR/USD", "15m", BASE, BASE + timedelta(hours=1),
            now=NOW, max_candles=max_candles,
        )
    assert provider.calls == 0


def test_backfill_rejects_unsupported_timeframe(tmp_path):
    service, provider, _ = make_service(tmp_path, [make_candle(0)])
    with pytest.raises(ValueError, match="Unsupported candle timeframe"):
        service.backfill(
            "EUR/USD", "2m", BASE, BASE + timedelta(hours=1), now=NOW
        )
    assert provider.calls == 0


def test_backfill_preserves_completed_chunks_if_later_chunk_fails(tmp_path):
    provider = WindowProvider(fail_on_call=2)
    storage = CandleStorage(tmp_path / "partial.db")
    service = HistoricalDataService(provider, storage)
    with pytest.raises(ProviderUnavailable):
        service.backfill(
            "EUR/USD", "15m", BASE, BASE + timedelta(minutes=45),
            now=NOW, max_candles=2,
        )
    assert storage.load_candles("EUR/USD", timeframe="15m") == [
        make_candle(0), make_candle(1)
    ]


def test_backfill_does_not_mix_timeframes(tmp_path):
    provider = WindowProvider()
    storage = CandleStorage(tmp_path / "separate.db")
    hourly = Candle("EUR/USD", BASE, 1.0, 1.3, 0.8, 1.2, 500.0)
    storage.save_candles([hourly], timeframe="1h")
    service = HistoricalDataService(provider, storage)
    service.backfill(
        "EUR/USD", "15m", BASE, BASE + timedelta(minutes=45),
        now=NOW, max_candles=2,
    )
    assert storage.load_candles("EUR/USD", timeframe="1h") == [hourly]


def test_backfill_rejects_empty_range_without_calling_provider(tmp_path):
    service, provider, _ = make_service(tmp_path, [make_candle(0)])
    with pytest.raises(ValueError, match="before end time"):
        service.backfill("EUR/USD", "15m", BASE, BASE, now=NOW)
    assert provider.calls == 0
