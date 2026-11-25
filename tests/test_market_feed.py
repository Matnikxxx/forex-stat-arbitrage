"""Tests for provider-neutral market-data ingestion and quality checks."""

from datetime import datetime, timedelta, timezone

import pytest

from src.market_data import Candle, CandleValidationError
from src.market_feed import (
    CandleRequest,
    MarketDataError,
    ProviderUnavailable,
    assess_data_quality,
    candles_to_close_prices,
    detect_candle_gaps,
    fetch_market_data,
    filter_closed_candles,
    merge_candle_series,
    timeframe_duration,
    validate_provider_candles,
    validate_request,
)


BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


def candle(index=0, pair="EUR/USD", close=1.1):
    return Candle(
        pair, BASE_TIME + timedelta(minutes=15 * index),
        close, close + 0.001, close - 0.001, close, 100.0,
    )


class FakeProvider:
    name = "fixture"

    def __init__(self, values=None, error=None):
        self.values = values if values is not None else [candle(0)]
        self.error = error
        self.request_seen = None

    def fetch_candles(self, request):
        self.request_seen = request
        if self.error:
            raise self.error
        return self.values


def test_valid_request_is_returned_unchanged():
    request = CandleRequest("EUR/USD", "15m", 250)
    assert validate_request(request) is request


@pytest.mark.parametrize("invalid_request", [
    CandleRequest("EURUSD", "15m"),
    CandleRequest("EUR/EUR", "15m"),
    CandleRequest("EUR/USD", "2m"),
    CandleRequest("EUR/USD", "15m", 0),
    CandleRequest("EUR/USD", "15m", 5001),
    CandleRequest("EUR/USD", "15m", True),
])
def test_invalid_requests_are_rejected(invalid_request):
    with pytest.raises(ValueError):
        validate_request(invalid_request)


def test_timeframe_duration_supports_configured_intervals():
    assert timeframe_duration("15m") == timedelta(minutes=15)
    assert timeframe_duration("1d") == timedelta(days=1)


def test_provider_candles_are_validated_and_pair_checked():
    request = CandleRequest("EUR/USD", "15m", 5)
    assert validate_provider_candles(request, [candle(0)]) == [candle(0)]
    with pytest.raises(MarketDataError, match="wrong pair"):
        validate_provider_candles(
            request, [candle(0, pair="GBP/USD")]
        )


def test_provider_output_cannot_exceed_requested_limit():
    request = CandleRequest("EUR/USD", "15m", 1)
    with pytest.raises(MarketDataError, match="more candles"):
        validate_provider_candles(request, [candle(0), candle(1)])


def test_empty_provider_output_is_rejected():
    with pytest.raises(MarketDataError, match="no candles"):
        validate_provider_candles(CandleRequest("EUR/USD", "15m"), [])


def test_fetch_market_data_passes_request_and_returns_valid_data():
    provider = FakeProvider([candle(0), candle(1)])
    request = CandleRequest("EUR/USD", "15m", 2)
    assert fetch_market_data(provider, request) == [candle(0), candle(1)]
    assert provider.request_seen is request


def test_fetch_market_data_wraps_provider_failure():
    provider = FakeProvider(error=OSError("offline"))
    with pytest.raises(ProviderUnavailable, match="failed"):
        fetch_market_data(provider, CandleRequest("EUR/USD", "15m"))


def test_filter_closed_candles_removes_forming_candle():
    values = [candle(0), candle(1), candle(2)]
    now = BASE_TIME + timedelta(minutes=37)
    result = filter_closed_candles(values, "15m", now)
    assert result == values[:2]


def test_filter_closed_candles_requires_timezone_aware_clock():
    with pytest.raises(ValueError, match="timezone"):
        filter_closed_candles([candle()], "15m", datetime(2026, 1, 1))


def test_merge_candle_series_sorts_and_deduplicates():
    older = candle(0)
    original = candle(1)
    replacement = candle(1, close=1.2)
    merged = merge_candle_series([original], [older, replacement])
    assert merged == [older, replacement]


def test_merge_candle_series_rejects_mixed_pairs():
    with pytest.raises(CandleValidationError, match="one pair"):
        merge_candle_series([candle(0)], [candle(1, pair="GBP/USD")])


def test_detect_candle_gaps_reports_missing_intervals():
    gaps = detect_candle_gaps([candle(0), candle(3)], "15m")
    assert len(gaps) == 2
    assert gaps[0].missing == BASE_TIME + timedelta(minutes=15)
    assert gaps[1].missing == BASE_TIME + timedelta(minutes=30)


def test_quality_report_calculates_coverage_and_missing_count():
    report = assess_data_quality([candle(0), candle(2)], "15m", 3)
    assert report.received == 2
    assert report.expected == 3
    assert report.missing == 1
    assert report.coverage == pytest.approx(2 / 3)
    assert len(report.gaps) == 1


def test_quality_report_rejects_impossible_expected_count():
    with pytest.raises(ValueError, match="at least received"):
        assess_data_quality([candle(0), candle(1)], "15m", 1)


def test_close_price_conversion_uses_validated_close_values():
    assert candles_to_close_prices([candle(0), candle(1)]) == [1.1, 1.1]


def test_close_price_conversion_rejects_empty_series():
    with pytest.raises(CandleValidationError, match="No market candles"):
        candles_to_close_prices([])
