"""Backfill execution integrated with persistent retry scheduling."""

from dataclasses import dataclass
from datetime import datetime

from src.backfill_execution import BackfillExecutionResult, execute_backfill_plan
from src.backfill_planner import BackfillPlan
from src.backfill_retry import BackfillRetrySchedule
from src.backfill_retry_manager import BackfillRetryManager
from src.historical_data import HistoricalDataService
from src.market_feed import ProviderUnavailable


@dataclass(frozen=True)
class ManagedBackfillResult:
    """Execution result plus any retry schedule created by the coordinator."""

    execution: BackfillExecutionResult
    retry_schedule: BackfillRetrySchedule | None


def execute_managed_backfill(
    service: HistoricalDataService,
    plan: BackfillPlan,
    retry_manager: BackfillRetryManager,
    now: datetime | None = None,
) -> ManagedBackfillResult:
    """Execute a backfill and synchronize retry metadata with its outcome.

    Quota deferrals are recorded. Other temporary provider outages are
    scheduled before the original exception is re-raised. Successful runs
    clear old retry state. Invalid plans are not retried. No workers, timers,
    sleeps, or background polling are started.
    """
    if not isinstance(service, HistoricalDataService):
        raise ValueError("A HistoricalDataService is required.")
    if not isinstance(plan, BackfillPlan):
        raise ValueError("A BackfillPlan is required.")
    if not isinstance(retry_manager, BackfillRetryManager):
        raise ValueError("A BackfillRetryManager is required.")

    try:
        execution = execute_backfill_plan(service, plan, now=now)
    except ProviderUnavailable as error:
        retry_manager.record_failure(
            plan.pair,
            plan.timeframe,
            now or datetime.now().astimezone(),
            provider_retry_after_seconds=getattr(error, "retry_after_seconds", 0.0),
        )
        raise

    if execution.deferred:
        schedule = retry_manager.record_failure(
            plan.pair,
            plan.timeframe,
            now or datetime.now().astimezone(),
            provider_retry_after_seconds=execution.retry_after_seconds,
        )
        return ManagedBackfillResult(execution, schedule)

    retry_manager.mark_completed(plan.pair, plan.timeframe)
    return ManagedBackfillResult(execution, None)
