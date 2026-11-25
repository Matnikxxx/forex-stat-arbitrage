"""Freshness and coverage monitoring for locally stored market candles."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from collections.abc import Sequence

from src.market_data import Candle, validate_candle_series
from src.market_feed import (
    CandleGap,
    assess_data_quality,
    timeframe_duration,
)


@dataclass(frozen=True)
class FeedHealth:
    """Immutable, dashboard-safe health summary for one candle feed."""

    pair: str
    timeframe: str
    status: str
    received: int
    latest_candle_at: datetime
    latest_closed_at: datetime
    age_seconds: float
    max_age_seconds: float
    gap_count: int
    missing_count: int
    coverage: float
    gaps: tuple[CandleGap, ...]
    issues: tuple[str, ...]


def assess_feed_health(
    candles: Sequence[Candle],
    timeframe: str,
    now: datetime | None = None,
    max_age: timedelta | None = None,
    expected_count: int | None = None,
) -> FeedHealth:
    """Assess whether a stored candle feed is fresh and sufficiently complete.

    The supplied series must contain validated, chronological candles for one
    pair. This function does not fetch data, fill gaps, or change stored data.
    The default freshness limit is two candle intervals.
    """
    if not candles:
        raise ValueError("At least one candle is required to assess feed health.")
    duration = timeframe_duration(timeframe)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("Current time must include a timezone.")
    current = current.astimezone(timezone.utc)

    limit = max_age if max_age is not None else duration * 2
    if not isinstance(limit, timedelta) or not isfinite(limit.total_seconds()):
        raise ValueError("Maximum age must be a finite timedelta.")
    if limit.total_seconds() <= 0:
        raise ValueError("Maximum age must be positive.")

    validated = validate_candle_series(list(candles))
    latest = validated[-1]
    latest_at = latest.timestamp.astimezone(timezone.utc)
    closed_at = latest_at + duration
    if closed_at > current:
        raise ValueError("Latest candle has not closed yet or is in the future.")

    age = (current - closed_at).total_seconds()
    quality = assess_data_quality(
        validated, timeframe, expected_count=expected_count
    )
    issues = []
    if age > limit.total_seconds():
        issues.append("Latest candle is stale.")
    if quality.gaps:
        issues.append("Candle history contains gaps.")
    if quality.missing > len(quality.gaps):
        issues.append("Expected candle coverage is incomplete.")

    if age > limit.total_seconds():
        status = "stale"
    elif issues:
        status = "warning"
    else:
        status = "healthy"

    return FeedHealth(
        pair=latest.pair,
        timeframe=timeframe,
        status=status,
        received=quality.received,
        latest_candle_at=latest_at,
        latest_closed_at=closed_at,
        age_seconds=age,
        max_age_seconds=limit.total_seconds(),
        gap_count=len(quality.gaps),
        missing_count=quality.missing,
        coverage=quality.coverage,
        gaps=quality.gaps,
        issues=tuple(issues),
    )
