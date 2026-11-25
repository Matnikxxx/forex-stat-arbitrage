"""High-level coordinator for persistent historical backfill retries."""

from datetime import datetime

from src.backfill_retry import BackfillRetrySchedule, schedule_backfill_retry
from src.backfill_retry_storage import BackfillRetryState, BackfillRetryStorage


class BackfillRetryManager:
    """Persist retry attempts and expose due work without running background jobs."""

    def __init__(
        self,
        storage: BackfillRetryStorage,
        base_delay_seconds: float = 5.0,
        max_delay_seconds: float = 300.0,
    ) -> None:
        if not isinstance(storage, BackfillRetryStorage):
            raise ValueError("BackfillRetryStorage is required.")
        self.storage = storage
        self.base_delay_seconds = base_delay_seconds
        self.max_delay_seconds = max_delay_seconds
        # Validate configured delay values through the public scheduler.
        schedule_backfill_retry(
            attempt=1,
            now=datetime.now().astimezone(),
            base_delay_seconds=base_delay_seconds,
            max_delay_seconds=max_delay_seconds,
        )

    def record_failure(
        self,
        pair: str,
        timeframe: str,
        now: datetime,
        provider_retry_after_seconds: float = 0.0,
    ) -> BackfillRetrySchedule:
        """Increment and persist the retry schedule after a temporary failure."""
        previous = self.storage.load(pair, timeframe)
        attempt = 1 if previous is None else previous.attempt + 1
        schedule = schedule_backfill_retry(
            attempt=attempt,
            now=now,
            base_delay_seconds=self.base_delay_seconds,
            max_delay_seconds=self.max_delay_seconds,
            provider_retry_after_seconds=provider_retry_after_seconds,
        )
        self.storage.save(
            BackfillRetryState(
                pair=pair,
                timeframe=timeframe,
                attempt=schedule.attempt,
                next_attempt_at=schedule.next_attempt_at,
                delay_seconds=schedule.delay_seconds,
                provider_delay_seconds=schedule.provider_delay_seconds,
            )
        )
        return schedule

    def due_retries(self, now: datetime) -> list[BackfillRetryState]:
        """List persisted retries ready for the caller to process."""
        return self.storage.load_due(now)

    def get_schedule(
        self, pair: str, timeframe: str
    ) -> BackfillRetryState | None:
        """Return the current retry schedule for one backfill."""
        return self.storage.load(pair, timeframe)

    def mark_completed(self, pair: str, timeframe: str) -> bool:
        """Remove retry metadata after the corresponding backfill succeeds."""
        return self.storage.delete(pair, timeframe)
