"""Tests for provider health tracking and circuit-breaker recovery."""

from datetime import datetime, timezone

import pytest

from src.market_data import Candle
from src.market_feed import CandleRequest, ProviderUnavailable
from src.provider_health import CircuitBreakingProvider


class FakeClock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class StubProvider:
    name = "stub"

    def __init__(self, result=None, error=None):
        self.result = result if result is not None else []
        self.error = error
        self.calls = 0

    def fetch_candles(self, request):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


REQUEST = CandleRequest("EUR/USD", "15m", 10)
SAMPLE = Candle(
    "EUR/USD",
    datetime(2026, 1, 1, tzinfo=timezone.utc),
    1.0,
    1.2,
    0.9,
    1.1,
    0.0,
)


def test_successful_provider_starts_closed():
    provider = CircuitBreakingProvider(StubProvider([SAMPLE]), clock=FakeClock())
    assert provider.state == "closed"


def test_success_increments_success_count():
    wrapped = CircuitBreakingProvider(
        StubProvider([SAMPLE]), clock=FakeClock()
    )
    assert wrapped.fetch_candles(REQUEST) == [SAMPLE]
    assert wrapped.health().total_successes == 1


def test_failure_increments_failure_count():
    wrapped = CircuitBreakingProvider(
        StubProvider(error=OSError("offline")), clock=FakeClock()
    )
    with pytest.raises(ProviderUnavailable):
        wrapped.fetch_candles(REQUEST)
    health = wrapped.health()
    assert health.total_failures == 1
    assert health.consecutive_failures == 1


def test_circuit_opens_at_failure_threshold():
    clock = FakeClock()
    wrapped = CircuitBreakingProvider(
        StubProvider(error=OSError("offline")),
        failure_threshold=2,
        clock=clock,
    )
    for _ in range(2):
        with pytest.raises(ProviderUnavailable):
            wrapped.fetch_candles(REQUEST)
    assert wrapped.state == "open"


def test_open_circuit_blocks_provider_calls():
    clock = FakeClock()
    stub = StubProvider(error=OSError("offline"))
    wrapped = CircuitBreakingProvider(
        stub, failure_threshold=1, clock=clock
    )
    with pytest.raises(ProviderUnavailable):
        wrapped.fetch_candles(REQUEST)
    calls = stub.calls
    with pytest.raises(ProviderUnavailable, match="circuit is open"):
        wrapped.fetch_candles(REQUEST)
    assert stub.calls == calls


def test_open_circuit_reports_remaining_cooldown():
    clock = FakeClock()
    wrapped = CircuitBreakingProvider(
        StubProvider(error=OSError("offline")),
        failure_threshold=1,
        reset_timeout=30,
        clock=clock,
    )
    with pytest.raises(ProviderUnavailable):
        wrapped.fetch_candles(REQUEST)
    clock.advance(10)
    assert wrapped.health().retry_after_seconds == 20


def test_expired_cooldown_enters_half_open_state():
    clock = FakeClock()
    wrapped = CircuitBreakingProvider(
        StubProvider(error=OSError("offline")),
        failure_threshold=1,
        reset_timeout=5,
        clock=clock,
    )
    with pytest.raises(ProviderUnavailable):
        wrapped.fetch_candles(REQUEST)
    clock.advance(5)
    assert wrapped.state == "half-open"


def test_successful_recovery_probe_closes_circuit():
    clock = FakeClock()
    stub = StubProvider(error=OSError("offline"))
    wrapped = CircuitBreakingProvider(
        stub, failure_threshold=1, reset_timeout=5, clock=clock
    )
    with pytest.raises(ProviderUnavailable):
        wrapped.fetch_candles(REQUEST)
    clock.advance(5)
    stub.error = None
    stub.result = [SAMPLE]
    assert wrapped.fetch_candles(REQUEST) == [SAMPLE]
    assert wrapped.state == "closed"


def test_failed_recovery_probe_reopens_circuit():
    clock = FakeClock()
    wrapped = CircuitBreakingProvider(
        StubProvider(error=OSError("offline")),
        failure_threshold=1,
        reset_timeout=5,
        clock=clock,
    )
    with pytest.raises(ProviderUnavailable):
        wrapped.fetch_candles(REQUEST)
    clock.advance(5)
    with pytest.raises(ProviderUnavailable):
        wrapped.fetch_candles(REQUEST)
    assert wrapped.state == "open"


def test_success_resets_consecutive_failure_count():
    wrapped = CircuitBreakingProvider(
        StubProvider([SAMPLE]), failure_threshold=3, clock=FakeClock()
    )
    wrapped._consecutive_failures = 2
    wrapped.fetch_candles(REQUEST)
    assert wrapped.health().consecutive_failures == 0


def test_health_snapshot_does_not_expose_error_message():
    wrapped = CircuitBreakingProvider(
        StubProvider(error=OSError("private credential text")),
        failure_threshold=1,
        clock=FakeClock(),
    )
    with pytest.raises(ProviderUnavailable):
        wrapped.fetch_candles(REQUEST)
    health = wrapped.health()
    assert health.last_error_type == "OSError"
    assert "private credential text" not in repr(health)


def test_invalid_threshold_and_timeout_are_rejected():
    stub = StubProvider([SAMPLE])
    with pytest.raises(ValueError):
        CircuitBreakingProvider(stub, failure_threshold=0)
    with pytest.raises(ValueError):
        CircuitBreakingProvider(stub, reset_timeout=0)


def test_successful_request_clears_previous_error_type():
    clock = FakeClock()
    stub = StubProvider(error=OSError("offline"))
    wrapped = CircuitBreakingProvider(stub, clock=clock)
    with pytest.raises(ProviderUnavailable):
        wrapped.fetch_candles(REQUEST)
    stub.error = None
    stub.result = [SAMPLE]
    wrapped.fetch_candles(REQUEST)
    assert wrapped.health().last_error_type is None


def test_circuit_stays_closed_below_failure_threshold():
    clock = FakeClock()
    wrapped = CircuitBreakingProvider(
        StubProvider(error=OSError("offline")),
        failure_threshold=2,
        clock=clock,
    )
    with pytest.raises(ProviderUnavailable):
        wrapped.fetch_candles(REQUEST)
    assert wrapped.state == "closed"
    assert wrapped.health().consecutive_failures == 1
