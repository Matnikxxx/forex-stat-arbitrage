from datetime import datetime, timedelta, timezone

import pytest

from src.backfill_planner import plan_backfill
from src.backfill_retry_manager import BackfillRetryManager
from src.backfill_retry_storage import BackfillRetryStorage
from src.backfill_retry_runner import execute_due_backfill
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
        self.calls = 0

    def fetch_candles(self, request):
        self.calls += 1
        if self.fail:
            raise ProviderUnavailable("temporary failure")
        step = timedelta(minutes=15)
        return [Candle(request.pair, request.start + step * i, 1.1, 1.2, 1.0, 1.1, 10)
                for i in range(int((request.end - request.start) / step) + 1)]


def build(tmp_path, provider):
    service = HistoricalDataService(provider, CandleStorage(tmp_path / "candles.db"))
    retries = BackfillRetryManager(BackfillRetryStorage(tmp_path / "retries.db"))
    plan = plan_backfill("EUR/USD", "15m", NOW, NOW + timedelta(minutes=75),
                         ProviderQuota(max_requests=20, window_seconds=60), max_candles=2)
    return service, retries, plan


def test_no_retry_means_no_provider_call(tmp_path):
    provider = Provider()
    service, retries, plan = build(tmp_path, provider)
    assert execute_due_backfill(service, plan, retries, NOW) is None
    assert provider.calls == 0


def test_future_retry_is_not_run(tmp_path):
    provider = Provider()
    service, retries, plan = build(tmp_path, provider)
    retries.record_failure("EUR/USD", "15m", NOW)
    assert execute_due_backfill(service, plan, retries, NOW + timedelta(seconds=4)) is None
    assert provider.calls == 0


def test_due_retry_runs_and_clears_schedule(tmp_path):
    service, retries, plan = build(tmp_path, Provider())
    schedule = retries.record_failure("EUR/USD", "15m", NOW)
    result = execute_due_backfill(service, plan, retries, schedule.next_attempt_at)
    assert result.execution.completed
    assert retries.get_schedule("EUR/USD", "15m") is None


def test_provider_error_is_rescheduled_and_reraised(tmp_path):
    service, retries, plan = build(tmp_path, Provider(fail=True))
    schedule = retries.record_failure("EUR/USD", "15m", NOW)
    with pytest.raises(ProviderUnavailable):
        execute_due_backfill(service, plan, retries, schedule.next_attempt_at)
    assert retries.get_schedule("EUR/USD", "15m").attempt == 2


def test_different_pair_does_not_consume_due_retry(tmp_path):
    provider = Provider()
    service, retries, _ = build(tmp_path, provider)
    retries.record_failure("EUR/USD", "15m", NOW)
    other = plan_backfill("GBP/USD", "15m", NOW, NOW + timedelta(minutes=75),
                          ProviderQuota(max_requests=20, window_seconds=60), max_candles=2)
    assert execute_due_backfill(service, other, retries, NOW + timedelta(days=1)) is None
    assert provider.calls == 0


def test_timezone_equivalent_due_time_is_accepted(tmp_path):
    service, retries, plan = build(tmp_path, Provider())
    schedule = retries.record_failure("EUR/USD", "15m", NOW)
    local_time = schedule.next_attempt_at.astimezone(timezone(timedelta(hours=2)))
    assert execute_due_backfill(service, plan, retries, local_time).execution.completed


@pytest.mark.parametrize("bad_now", [None, "2026-01-01", NOW.replace(tzinfo=None)])
def test_invalid_now_is_rejected(tmp_path, bad_now):
    service, retries, plan = build(tmp_path, Provider())
    with pytest.raises(ValueError, match="Current time"):
        execute_due_backfill(service, plan, retries, bad_now)


@pytest.mark.parametrize("service_arg,plan_arg,retry_arg", [(None, "valid", "valid"), ("valid", None, "valid"), ("valid", "valid", None)])
def test_invalid_dependencies_are_rejected(tmp_path, service_arg, plan_arg, retry_arg):
    service, retries, plan = build(tmp_path, Provider())
    with pytest.raises(ValueError):
        execute_due_backfill(service_arg if service_arg != "valid" else service,
                             plan_arg if plan_arg != "valid" else plan,
                             retry_arg if retry_arg != "valid" else retries, NOW)
