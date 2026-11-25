"""Tests for ordered provider failover and safe failure behaviour."""

from datetime import datetime, timezone

import pytest

from src.market_data import Candle
from src.market_feed import (
    CandleRequest,
    MarketDataError,
    ProviderUnavailable,
)
from src.provider_failover import FallbackMarketDataProvider


STAMP = datetime(2026, 1, 1, tzinfo=timezone.utc)


def candle(close=1.1, pair="EUR/USD"):
    return Candle(pair, STAMP, 1.0, 1.2, 0.9, close, 0.0)


class StubProvider:
    def __init__(self, name, result=None, error=None):
        self.name = name
        self.result = result
        self.error = error
        self.calls = 0

    def fetch_candles(self, request):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


REQUEST = CandleRequest("EUR/USD", "15m", 10)


def test_primary_provider_is_used_when_available():
    primary = StubProvider("primary", [candle()])
    fallback = StubProvider("fallback", [candle(1.2)])
    chain = FallbackMarketDataProvider([primary, fallback])

    result = chain.fetch_with_report(REQUEST)

    assert result.provider == "primary"
    assert result.candles[0].close == 1.1
    assert primary.calls == 1
    assert fallback.calls == 0


def test_fallback_is_used_when_primary_unavailable():
    primary = StubProvider("primary", error=ProviderUnavailable("offline"))
    fallback = StubProvider("fallback", [candle()])
    chain = FallbackMarketDataProvider([primary, fallback])

    result = chain.fetch_with_report(REQUEST)

    assert result.provider == "fallback"
    assert [attempt.provider for attempt in result.attempts] == [
        "primary", "fallback"
    ]
    assert [attempt.succeeded for attempt in result.attempts] == [False, True]


def test_provider_order_is_preserved():
    first = StubProvider("first", error=ProviderUnavailable("offline"))
    second = StubProvider("second", [candle()])
    third = StubProvider("third", [candle(1.3)])
    chain = FallbackMarketDataProvider([first, second, third])

    result = chain.fetch_with_report(REQUEST)

    assert result.provider == "second"
    assert third.calls == 0


def test_all_unavailable_raises_clear_error():
    first = StubProvider("first", error=ProviderUnavailable("offline"))
    second = StubProvider("second", error=ProviderUnavailable("offline"))
    chain = FallbackMarketDataProvider([first, second])

    with pytest.raises(ProviderUnavailable, match="first, second"):
        chain.fetch_candles(REQUEST)


def test_empty_provider_list_is_rejected():
    with pytest.raises(ValueError, match="at least one"):
        FallbackMarketDataProvider([])


def test_duplicate_provider_names_are_rejected():
    with pytest.raises(ValueError, match="unique"):
        FallbackMarketDataProvider([
            StubProvider("same", [candle()]),
            StubProvider("same", [candle()]),
        ])


def test_missing_provider_name_is_rejected():
    with pytest.raises(ValueError, match="non-empty"):
        FallbackMarketDataProvider([StubProvider("", [candle()])])


def test_invalid_data_does_not_trigger_fallback():
    primary = StubProvider("primary", [candle(pair="GBP/USD")])
    fallback = StubProvider("fallback", [candle()])
    chain = FallbackMarketDataProvider([primary, fallback])

    with pytest.raises(MarketDataError, match="wrong pair"):
        chain.fetch_candles(REQUEST)

    assert fallback.calls == 0


def test_malformed_candle_series_does_not_trigger_fallback():
    primary = StubProvider("primary", [candle(), candle()])
    fallback = StubProvider("fallback", [candle()])
    chain = FallbackMarketDataProvider([primary, fallback])

    with pytest.raises(MarketDataError, match="invalid candles"):
        chain.fetch_candles(REQUEST)

    assert fallback.calls == 0


def test_generic_provider_exception_is_wrapped_and_falls_back():
    primary = StubProvider("primary", error=RuntimeError("connection reset"))
    fallback = StubProvider("fallback", [candle()])
    chain = FallbackMarketDataProvider([primary, fallback])

    result = chain.fetch_with_report(REQUEST)

    assert result.provider == "fallback"
    assert result.attempts[0].error_type == "ProviderUnavailable"


def test_successful_result_is_remembered():
    chain = FallbackMarketDataProvider([StubProvider("primary", [candle()])])

    result = chain.fetch_with_report(REQUEST)

    assert chain.last_result == result


def test_failed_run_clears_previous_success_metadata():
    first = StubProvider("first", [candle()])
    second = StubProvider("second", error=ProviderUnavailable("offline"))
    chain = FallbackMarketDataProvider([first, second])
    chain.fetch_with_report(REQUEST)
    chain.providers = (second,)

    with pytest.raises(ProviderUnavailable):
        chain.fetch_with_report(REQUEST)

    assert chain.last_result is None


def test_bad_request_is_rejected_before_calling_providers():
    primary = StubProvider("primary", [candle()])
    chain = FallbackMarketDataProvider([primary])

    with pytest.raises(ValueError):
        chain.fetch_candles(CandleRequest("EUR/USD", "2h", 10))

    assert primary.calls == 0


def test_provider_attempt_report_contains_no_error_message_or_secrets():
    primary = StubProvider(
        "primary",
        error=ProviderUnavailable("secret-api-key must not leak"),
    )
    fallback = StubProvider("fallback", [candle()])
    result = FallbackMarketDataProvider([primary, fallback]).fetch_with_report(
        REQUEST
    )

    assert "secret-api-key" not in repr(result)
    assert result.attempts[0].error_type == "ProviderUnavailable"


def test_provider_result_is_immutable():
    result = FallbackMarketDataProvider([
        StubProvider("primary", [candle()])
    ]).fetch_with_report(REQUEST)

    with pytest.raises(AttributeError):
        result.provider = "changed"
