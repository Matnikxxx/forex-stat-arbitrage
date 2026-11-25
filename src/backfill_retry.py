"""Deterministic, quota-respecting retry scheduling for historical backfills."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math


@dataclass(frozen=True)
class BackfillRetrySchedule:
    """A single future retry decision; this module never sleeps or retries."""

    attempt: int
    delay_seconds: float
    next_attempt_at: datetime
    provider_delay_seconds: float


def schedule_backfill_retry(
    attempt: int,
    now: datetime,
    base_delay_seconds: float = 5.0,
    max_delay_seconds: float = 300.0,
    provider_retry_after_seconds: float = 0.0,
) -> BackfillRetrySchedule:
    """Calculate capped exponential backoff while honoring provider Retry-After.

    Attempts are one-based. The provider delay is a lower bound, so a local
    backoff calculation can never schedule earlier than the provider permits.
    No timer, sleep, network request, or background worker is started.
    """
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise ValueError("Attempt must be a positive integer.")
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Current time must include a timezone.")

    for label, value, allow_zero in (
        ("Base delay", base_delay_seconds, False),
        ("Maximum delay", max_delay_seconds, False),
        ("Provider retry delay", provider_retry_after_seconds, True),
    ):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or (value < 0 if allow_zero else value <= 0)
        ):
            qualifier = "non-negative" if allow_zero else "positive"
            raise ValueError(f"{label} must be a finite {qualifier} number.")

    if max_delay_seconds < base_delay_seconds:
        raise ValueError("Maximum delay must be at least the base delay.")

    cap_attempt = math.ceil(math.log2(max_delay_seconds / base_delay_seconds))
    if attempt - 1 >= cap_attempt:
        local_delay = max_delay_seconds
    else:
        local_delay = base_delay_seconds * (2 ** (attempt - 1))
    delay = max(local_delay, float(provider_retry_after_seconds))
    current = now.astimezone(timezone.utc)

    return BackfillRetrySchedule(
        attempt=attempt,
        delay_seconds=delay,
        next_attempt_at=current + timedelta(seconds=delay),
        provider_delay_seconds=float(provider_retry_after_seconds),
    )
