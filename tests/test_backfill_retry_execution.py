from datetime import datetime, timedelta, timezone

import pytest

from src.backfill_planner import plan_backfill
from src.backfill_retry_execution import execute_managed_backfill
from src.backfill_retry_manager import BackfillRetryManager
from src.backfill_retry_storage import BackfillRetryStorage
from src.historical_data import HistoricalDataService
from src.market_data import Candle
from src.market_feed import ProviderUnavailable
from src.market_storage import CandleStorage
from src.provider_quota import ProviderQuota

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class Provider:
    name = "test"

    def __init__(self, fail=False):
        self.fail = fail

    def fetch_candles(self, request):
        if self.fail:
            raise ProviderUnavailable("temporary failure")
        step = timedelta(minutes=15)
        return [
            Candle(request.pair, request.start + step * i, 1.1, 1.2, 1.0, 1.1, 10)
            for i in range(int((request.end - request.start) / step) + 1)
        ]


def build(tmp_path, provider):
    service = HistoricalDataService(
        provider, CandleStorage(tmp_path / "candles.db")
    )
    retries = BackfillRetryManager(
        BackfillRetryStorage(tmp_path / "retries.db")
    )
    plan = plan_backfill(
        "EUR/USD", "15m", NOW, NOW + timedelta(minutes=75),
        ProviderQuota(max_requests=20, window_seconds=60), max_candles=2,
    )
    return service, retries, plan


def test_success_clears_previous_retry(tmp_path):
    service, retries, plan = build(tmp_path, Provider())
    retries.record_failure("EUR/USD", "15m", NOW)
    result = execute_managed_backfill(service, plan, retries, now=NOW + timedelta(days=1))
    assert result.execution.completed
    assert result.retry_schedule is None
    assert retries.get_schedule("EUR/USD", "15m") is None


def test_provider_failure_is_scheduled_and_reraised(tmp_path):
    service, retries, plan = build(tmp_path, Provider(fail=True))
    with pytest.raises(ProviderUnavailable, match="temporary failure"):
        execute_managed_backfill(service, plan, retries, now=NOW)
    assert retries.get_schedule("EUR/USD", "15m").attempt == 1


def test_repeated_failures_increment_attempt(tmp_path):
    service, retries, plan = build(tmp_path, Provider(fail=True))
    for _ in range(2):
        with pytest.raises(ProviderUnavailable):
            execute_managed_backfill(service, plan, retries, now=NOW)
    assert retries.get_schedule("EUR/USD", "15m").attempt == 2


def test_invalid_plan_does_not_create_retry(tmp_path):
    service, retries, plan = build(tmp_path, Provider())
    with pytest.raises(ValueError):
        execute_managed_backfill(service, object(), retries, now=NOW)
    assert retries.get_schedule("EUR/USD", "15m") is None
