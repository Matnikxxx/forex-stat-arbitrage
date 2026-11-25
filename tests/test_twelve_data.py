"""Unit tests for the Twelve Data provider adapter; no network calls are made."""

import json
from datetime import datetime, timezone
from email.message import Message
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse

import pytest

from src.market_feed import CandleRequest, MarketDataError, ProviderUnavailable
from src.twelve_data import (
    TwelveDataProvider,
    TwelveDataRateLimitError,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.payload


def payload(*values):
    return {"meta": {"symbol": "EUR/USD"}, "values": list(values)}


def value(stamp="2026-01-01 00:15:00", close="1.1"):
    return {
        "datetime": stamp,
        "open": "1.09",
        "high": "1.12",
        "low": "1.08",
        "close": close,
        "volume": "0",
    }


def provider(monkeypatch, responses, **kwargs):
    queue = list(responses)
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        response = queue.pop(0)
        if isinstance(response, Exception):
            raise response
        return FakeResponse(response)

    monkeypatch.setattr("src.twelve_data.urlopen", fake_urlopen)
    monkeypatch.setattr("src.twelve_data.time.sleep", lambda _: None)
    instance = TwelveDataProvider("test-secret", retry_delay=0, **kwargs)
    return instance, calls


def test_fetch_parses_candles_and_normalizes_utc(monkeypatch):
    instance, _ = provider(monkeypatch, [payload(value())])

    candles = instance.fetch_candles(CandleRequest("EUR/USD", "15m"))

    assert len(candles) == 1
    assert candles[0].pair == "EUR/USD"
    assert candles[0].close == 1.1
    assert candles[0].timestamp == datetime(2026, 1, 1, 0, 15, tzinfo=timezone.utc)


def test_fetch_sorts_descending_provider_values(monkeypatch):
    instance, _ = provider(
        monkeypatch,
        [payload(value("2026-01-01 00:30:00"), value("2026-01-01 00:15:00"))],
    )

    candles = instance.fetch_candles(CandleRequest("EUR/USD", "15m"))

    assert candles[0].timestamp < candles[1].timestamp


@pytest.mark.parametrize(
    ("timeframe", "expected"),
    [
        ("1m", "1min"), ("5m", "5min"), ("15m", "15min"),
        ("30m", "30min"), ("1h", "1h"), ("4h", "4h"), ("1d", "1day"),
    ],
)
def test_request_maps_supported_timeframes(monkeypatch, timeframe, expected):
    instance, calls = provider(monkeypatch, [payload(value())])
    instance.fetch_candles(CandleRequest("EUR/USD", timeframe, 23))

    query = parse_qs(urlparse(calls[0][0].full_url).query)
    assert query["interval"] == [expected]
    assert query["outputsize"] == ["23"]
    assert query["timezone"] == ["UTC"]


def test_api_key_is_sent_in_header_not_url(monkeypatch):
    instance, calls = provider(monkeypatch, [payload(value())])
    instance.fetch_candles(CandleRequest("EUR/USD", "15m"))

    request = calls[0][0]
    assert request.get_header("Authorization") == "apikey test-secret"
    assert "test-secret" not in request.full_url


def test_missing_api_key_is_rejected(monkeypatch):
    monkeypatch.delenv("TWELVE_DATA_API_KEY", raising=False)

    with pytest.raises(ValueError, match="TWELVE_DATA_API_KEY"):
        TwelveDataProvider()


def test_api_key_can_be_loaded_from_environment(monkeypatch):
    monkeypatch.setenv("TWELVE_DATA_API_KEY", "environment-secret")

    instance = TwelveDataProvider()

    assert instance.api_key == "environment-secret"


def test_missing_candle_values_are_rejected(monkeypatch):
    instance, _ = provider(monkeypatch, [{"meta": {}}])

    with pytest.raises(MarketDataError, match="no candle"):
        instance.fetch_candles(CandleRequest("EUR/USD", "15m"))


def test_malformed_json_is_rejected(monkeypatch):
    monkeypatch.setattr(
        "src.twelve_data.urlopen",
        lambda *args, **kwargs: FakeResponse({"unexpected": "shape"}),
    )
    instance = TwelveDataProvider("test-secret", retry_delay=0)

    with pytest.raises(MarketDataError, match="no candle"):
        instance.fetch_candles(CandleRequest("EUR/USD", "15m"))


def test_invalid_ohlc_values_are_rejected_by_market_feed_validation(monkeypatch):
    instance, _ = provider(
        monkeypatch,
        [payload({**value(), "high": "1.0"})],
    )

    candles = instance.fetch_candles(CandleRequest("EUR/USD", "15m"))
    from src.market_feed import validate_provider_candles

    with pytest.raises(MarketDataError, match="invalid candles"):
        validate_provider_candles(CandleRequest("EUR/USD", "15m"), candles)


def test_api_error_payload_is_rejected(monkeypatch):
    instance, _ = provider(
        monkeypatch,
        [{"status": "error", "code": 400, "message": "Invalid symbol"}],
    )

    with pytest.raises(MarketDataError, match="Invalid symbol"):
        instance.fetch_candles(CandleRequest("EUR/USD", "15m"))


def test_api_rate_limit_is_reported_without_retry_for_json_error(monkeypatch):
    instance, calls = provider(
        monkeypatch,
        [{"status": "error", "code": 429, "message": "credits"}],
    )

    with pytest.raises(TwelveDataRateLimitError):
        instance.fetch_candles(CandleRequest("EUR/USD", "15m"))

    assert len(calls) == 1


def test_temporary_network_failure_is_retried(monkeypatch):
    instance, calls = provider(
        monkeypatch,
        [URLError("offline"), payload(value())],
        max_retries=1,
    )

    candles = instance.fetch_candles(CandleRequest("EUR/USD", "15m"))

    assert len(candles) == 1
    assert len(calls) == 2


def test_retries_are_bounded(monkeypatch):
    instance, calls = provider(
        monkeypatch,
        [URLError("offline"), URLError("offline"), URLError("offline")],
        max_retries=2,
    )

    with pytest.raises(ProviderUnavailable):
        instance.fetch_candles(CandleRequest("EUR/USD", "15m"))

    assert len(calls) == 3


def test_http_unauthorized_is_not_retried(monkeypatch):
    headers = Message()
    error = HTTPError("https://api.twelvedata.com", 401, "Unauthorized", headers, None)
    instance, calls = provider(monkeypatch, [error], max_retries=2)

    with pytest.raises(MarketDataError, match="rejected"):
        instance.fetch_candles(CandleRequest("EUR/USD", "15m"))

    assert len(calls) == 1


def test_http_rate_limit_is_retried_then_raised(monkeypatch):
    headers = Message()
    error = HTTPError("https://api.twelvedata.com", 429, "Too Many Requests", headers, None)
    instance, calls = provider(monkeypatch, [error, error], max_retries=1)

    with pytest.raises(TwelveDataRateLimitError):
        instance.fetch_candles(CandleRequest("EUR/USD", "15m"))

    assert len(calls) == 2


def test_limit_is_enforced_against_provider_response(monkeypatch):
    instance, _ = provider(monkeypatch, [payload(value(), value("2026-01-01 00:30:00"))])

    with pytest.raises(MarketDataError, match="more candles"):
        instance.fetch_candles(CandleRequest("EUR/USD", "15m", 1))


def test_malformed_timestamp_is_rejected(monkeypatch):
    instance, _ = provider(monkeypatch, [payload(value("not-a-date"))])

    with pytest.raises(MarketDataError, match="timestamp"):
        instance.fetch_candles(CandleRequest("EUR/USD", "15m"))


def test_non_numeric_candle_is_rejected(monkeypatch):
    instance, _ = provider(monkeypatch, [payload({**value(), "close": "bad"})])

    with pytest.raises(MarketDataError, match="non-numeric"):
        instance.fetch_candles(CandleRequest("EUR/USD", "15m"))


def test_provider_can_be_used_by_historical_service_contract(monkeypatch):
    instance, _ = provider(monkeypatch, [payload(value())])

    assert instance.name == "twelve_data"
    assert callable(instance.fetch_candles)



@pytest.mark.parametrize(
    "settings",
    [
        {"timeout": 0},
        {"timeout": float("inf")},
        {"max_retries": -1},
        {"max_retries": 1.5},
        {"retry_delay": -0.1},
        {"retry_delay": float("nan")},
    ],
)
def test_invalid_provider_settings_are_rejected(settings):
    with pytest.raises(ValueError):
        TwelveDataProvider("test-secret", **settings)
