"""Tests for quota-aware backfill execution and resumable deferrals."""

from datetime import datetime, timedelta, timezone

import pytest

from src.backfill_execution import execute_backfill_plan
from src.backfill_planner import plan_backfill
from src.historical_data import HistoricalDataService
from src.market_data import Candle
from src.market_feed import ProviderUnavailable
from src.market_storage import CandleStorage
from src.provider_quota import (
    ProviderQuota,
    ProviderQuotaExceeded,
    ProviderRequestGovernor,
)

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


class StubProvider:
    name = "stub"

    def __init__(self, governor=None, fail_after=None):
        self.governor = governor
        self.calls = 0
        self.fail_after = fail_after

    def fetch_candles(self, request):
        if self.fail_after is not None and self.calls >= self.fail_after:
            raise ProviderUnavailable("temporary outage")
        if self.governor is not None:
            decision = self.governor.acquire(START + timedelta(seconds=self.calls))
            if not decision.allowed:
                raise ProviderQuotaExceeded(self.name, decision.retry_after_seconds)
        self.calls += 1
        duration = {
            "15m": timedelta(minutes=15),
            "1h": timedelta(hours=1),
        }[request.timeframe]
        return [
            Candle(
                pair=request.pair,
                timestamp=request.start + duration * index,
                open=1.1,
                high=1.2,
                low=1.0,
                close=1.1,
                volume=100,
            )
            for index in range(
                int((request.end - request.start) / duration) + 1
            )
        ]


@pytest.fixture
def storage():
    instance = CandleStorage(":memory:")
    yield instance
    instance.close()


def make_plan(quota, max_candles=2):
    return plan_backfill(
        "EUR/USD", "15m", START, START + timedelta(minutes=75),
        quota, max_candles=max_candles,
    )


def test_execution_completes_all_planned_requests(storage):
    quota = ProviderQuota(max_requests=10, window_seconds=60)
    provider = StubProvider()
    service = HistoricalDataService(provider, storage)
    plan = make_plan(quota)

    result = execute_backfill_plan(service, plan, now=START + timedelta(days=1))

    assert result.completed is True
    assert result.deferred is False
    assert result.completed_requests == len(plan.requests)
    assert result.total_requests == len(plan.requests)
    assert result.retry_after_seconds == 0
    assert result.backfill_result is not None


def test_execution_defers_when_quota_is_exhausted(storage):
    quota = ProviderQuota(max_requests=1, window_seconds=60)
    governor = ProviderRequestGovernor(quota)
    provider = StubProvider(governor=governor)
    service = HistoricalDataService(provider, storage)
    plan = make_plan(quota)

    result = execute_backfill_plan(service, plan, now=START + timedelta(days=1))

    assert result.completed is False
    assert result.deferred is True
    assert result.completed_requests == 1
    assert result.total_requests == 3
    assert result.retry_after_seconds > 0
    assert result.backfill_result is None
    assert storage.load_backfill_checkpoint("EUR/USD", "15m") is not None


def test_execution_does_not_hide_non_quota_provider_errors(storage):
    provider = StubProvider(fail_after=0)
    service = HistoricalDataService(provider, storage)
    plan = make_plan(ProviderQuota(max_requests=10, window_seconds=60))

    with pytest.raises(ProviderUnavailable):
        execute_backfill_plan(service, plan, now=START + timedelta(days=1))


def test_execution_rejects_invalid_service_and_plan():
    with pytest.raises(ValueError, match="HistoricalDataService"):
        execute_backfill_plan(object(), object())
