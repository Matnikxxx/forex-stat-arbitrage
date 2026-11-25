"""Safe execution of preflighted, quota-aware historical backfills."""

from dataclasses import dataclass

from src.backfill_planner import BackfillPlan
from src.historical_data import HistoricalBackfillResult, HistoricalDataService
from src.provider_quota import ProviderQuotaExceeded


@dataclass(frozen=True)
class BackfillExecutionResult:
    """Execution outcome, including resumable progress after quota deferral."""

    completed: bool
    deferred: bool
    completed_requests: int
    total_requests: int
    stored_candles: int
    retry_after_seconds: float
    backfill_result: HistoricalBackfillResult | None


def execute_backfill_plan(
    service: HistoricalDataService,
    plan: BackfillPlan,
    now=None,
) -> BackfillExecutionResult:
    """Run a plan through the service and safely report quota-based deferrals.

    HistoricalDataService persists a checkpoint after each successful chunk.
    If the quota governor blocks a later request, this function returns a
    deferred outcome rather than busy-waiting or retrying in a loop. Calling it
    again with the same plan resumes from the persisted checkpoint.
    """
    if not isinstance(service, HistoricalDataService):
        raise ValueError("A HistoricalDataService is required.")
    if not isinstance(plan, BackfillPlan):
        raise ValueError("A BackfillPlan is required.")

    try:
        result = service.backfill(
            pair=plan.pair,
            timeframe=plan.timeframe,
            start=plan.start,
            end=plan.end,
            now=now,
            max_candles=plan.max_candles_per_request,
        )
    except ProviderQuotaExceeded as error:
        checkpoint = service.storage.load_backfill_checkpoint(
            plan.pair, plan.timeframe
        )
        cursor = checkpoint[2] if checkpoint is not None else plan.start
        completed = sum(1 for request in plan.requests if request.end < cursor)
        stored = len(
            service.load_history(plan.pair, timeframe=plan.timeframe)
        )
        return BackfillExecutionResult(
            completed=False,
            deferred=True,
            completed_requests=completed,
            total_requests=len(plan.requests),
            stored_candles=stored,
            retry_after_seconds=error.retry_after_seconds,
            backfill_result=None,
        )

    return BackfillExecutionResult(
        completed=True,
        deferred=False,
        completed_requests=result.request_count,
        total_requests=len(plan.requests),
        stored_candles=result.stored_count,
        retry_after_seconds=0.0,
        backfill_result=result,
    )
