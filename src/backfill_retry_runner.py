"""Execution gate for persisted backfill retries that have become due."""

from datetime import datetime, timezone

from src.backfill_planner import BackfillPlan
from src.backfill_retry_execution import ManagedBackfillResult, execute_managed_backfill
from src.backfill_retry_manager import BackfillRetryManager
from src.historical_data import HistoricalDataService


def execute_due_backfill(
    service: HistoricalDataService,
    plan: BackfillPlan,
    retry_manager: BackfillRetryManager,
    now: datetime,
) -> ManagedBackfillResult | None:
    """Run one persisted retry only when its scheduled UTC time has arrived.

    The caller supplies the original plan so date-range and candle-limit
    choices remain explicit. Missing or future retries are no-ops. Failures
    remain visible and are rescheduled by the managed executor. No polling,
    sleeps, workers, or trading actions are started.
    """
    if not isinstance(service, HistoricalDataService):
        raise ValueError("A HistoricalDataService is required.")
    if not isinstance(plan, BackfillPlan):
        raise ValueError("A BackfillPlan is required.")
    if not isinstance(retry_manager, BackfillRetryManager):
        raise ValueError("A BackfillRetryManager is required.")
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Current time must include a timezone.")

    state = retry_manager.get_schedule(plan.pair, plan.timeframe)
    if state is None:
        return None
    current = now.astimezone(timezone.utc)
    if state.next_attempt_at.astimezone(timezone.utc) > current:
        return None
    return execute_managed_backfill(service, plan, retry_manager, now=current)
