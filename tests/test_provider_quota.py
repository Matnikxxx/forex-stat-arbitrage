"""Tests for rolling provider quotas and request throttling."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from src.market_feed import CandleRequest, ProviderUnavailable
from src.provider_quota import (
    ProviderQuota,
    ProviderQuotaExceeded,
    ProviderRequestGovernor,
    QuotaAwareProvider,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class CountingProvider:
    name = "counting"

    def __init__(self):
        self.calls = 0

    def fetch_candles(self, request):
        self.calls += 1
        return ["provider-result"]


@pytest.mark.parametrize("quota", [
    ProviderQuota(1, 60),
    ProviderQuota(10, 1, 0.1),
])
def test_valid_quota_settings_are_accepted(quota):
    assert quota.max_requests > 0


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_invalid_request_limits_are_rejected(limit):
    with pytest.raises(ValueError, match="Maximum requests"):
        ProviderQuota(limit, 60)


@pytest.mark.parametrize("window", [0, -1, float("inf"), float("nan"), True])
def test_invalid_window_is_rejected(window):
    with pytest.raises(ValueError, match="Window"):
        ProviderQuota(5, window)


@pytest.mark.parametrize("interval", [-1, float("inf"), float("nan"), True])
def test_invalid_minimum_interval_is_rejected(interval):
    with pytest.raises(ValueError, match="Minimum interval"):
        ProviderQuota(5, 60, interval)


def test_rolling_window_blocks_until_oldest_request_expires():
    governor = ProviderRequestGovernor(ProviderQuota(2, 60))
    assert governor.acquire(NOW).allowed
    assert governor.acquire(NOW + timedelta(seconds=1)).allowed
    blocked = governor.acquire(NOW + timedelta(seconds=2))
    assert not blocked.allowed
    assert blocked.retry_after_seconds == 58
    assert governor.acquire(NOW + timedelta(seconds=60)).allowed


def test_minimum_interval_blocks_too_rapid_requests():
    governor = ProviderRequestGovernor(ProviderQuota(10, 60, 5))
    assert governor.acquire(NOW).allowed
    blocked = governor.acquire(NOW + timedelta(seconds=2))
    assert not blocked.allowed
    assert blocked.retry_after_seconds == 3
    assert governor.acquire(NOW + timedelta(seconds=5)).allowed


def test_snapshot_does_not_consume_quota():
    governor = ProviderRequestGovernor(ProviderQuota(1, 60))
    assert governor.snapshot(NOW).remaining == 1
    assert governor.snapshot(NOW).remaining == 1
    assert governor.acquire(NOW).remaining == 0


def test_cooldown_blocks_requests_until_expiry():
    governor = ProviderRequestGovernor(ProviderQuota(5, 60))
    until = governor.defer(30, NOW)
    blocked = governor.acquire(NOW + timedelta(seconds=10))
    assert not blocked.allowed
    assert blocked.retry_after_seconds == 20
    assert governor.acquire(until).allowed


def test_longer_cooldown_is_not_shortened():
    governor = ProviderRequestGovernor(ProviderQuota(5, 60))
    governor.defer(60, NOW)
    until = governor.defer(10, NOW + timedelta(seconds=5))
    assert until == NOW + timedelta(seconds=60)


@pytest.mark.parametrize("seconds", [-1, True, float("inf"), float("nan")])
def test_invalid_cooldown_is_rejected(seconds):
    governor = ProviderRequestGovernor(ProviderQuota(5, 60))
    with pytest.raises(ValueError, match="Cooldown"):
        governor.defer(seconds, NOW)


def test_naive_clock_is_rejected():
    governor = ProviderRequestGovernor(ProviderQuota(5, 60))
    with pytest.raises(ValueError, match="timezone"):
        governor.acquire(datetime(2026, 1, 1))


def test_wrapper_blocks_provider_call_when_quota_is_exhausted():
    provider = CountingProvider()
    governor = ProviderRequestGovernor(ProviderQuota(1, 60))
    wrapped = QuotaAwareProvider(provider, governor, clock=lambda: NOW)
    request = CandleRequest("EUR/USD", "15m")
    assert wrapped.fetch_candles(request) == ["provider-result"]
    with pytest.raises(ProviderQuotaExceeded):
        wrapped.fetch_candles(request)
    assert provider.calls == 1


def test_quota_exception_is_compatible_with_provider_failover():
    error = ProviderQuotaExceeded("test", 5)
    assert isinstance(error, ProviderUnavailable)
    assert error.retry_after_seconds == 5


def test_failed_provider_attempt_still_consumes_request_quota():
    class FailingProvider(CountingProvider):
        def fetch_candles(self, request):
            self.calls += 1
            raise ProviderUnavailable("offline")

    provider = FailingProvider()
    wrapped = QuotaAwareProvider(
        provider,
        ProviderRequestGovernor(ProviderQuota(1, 60)),
        clock=lambda: NOW,
    )
    request = CandleRequest("EUR/USD", "15m")
    with pytest.raises(ProviderUnavailable, match="offline"):
        wrapped.fetch_candles(request)
    with pytest.raises(ProviderQuotaExceeded):
        wrapped.fetch_candles(request)
    assert provider.calls == 1


def test_concurrent_acquisition_never_exceeds_quota():
    governor = ProviderRequestGovernor(ProviderQuota(7, 60))
    with ThreadPoolExecutor(max_workers=20) as pool:
        decisions = list(pool.map(lambda _: governor.acquire(NOW), range(20)))
    assert sum(decision.allowed for decision in decisions) == 7


def test_quota_is_available_again_after_full_window():
    governor = ProviderRequestGovernor(ProviderQuota(1, 10))
    assert governor.acquire(NOW).allowed
    assert governor.snapshot(NOW + timedelta(seconds=9)).allowed is False
    assert governor.snapshot(NOW + timedelta(seconds=10)).allowed is True
