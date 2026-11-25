"""Preflight planning for quota-aware historical backfills."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math

from src.market_feed import CandleRequest, timeframe_duration, validate_request
from src.provider_quota import ProviderQuota, ProviderRequestGovernor


@dataclass(frozen=True)
class BackfillPlan:
    """Immutable estimate of the requests and quota windows a backfill needs."""

    pair: str
    timeframe: str
    start: datetime
    end: datetime
    estimated_candles: int
    max_candles_per_request: int
    requests: tuple[CandleRequest, ...]
    quota_batches: tuple[tuple[CandleRequest, ...], ...]
    quota_windows_required: int
    estimated_wait_seconds: float
    requests_available_now: int
    can_start_now: bool
    retry_after_seconds: float


def plan_backfill(
    pair: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    quota: ProviderQuota,
    max_candles: int = 5000,
    governor: ProviderRequestGovernor | None = None,
    now: datetime | None = None,
) -> BackfillPlan:
    """Estimate bounded backfill requests and group them into quota-sized batches.

    The planner does not call a provider or modify storage. It uses inclusive
    candle endpoints and the same non-overlapping chunk boundaries as
    HistoricalDataService.backfill. Quota values are local configuration, not
    a claim about remote account credits.
    """
    if not isinstance(start, datetime) or start.tzinfo is None or start.utcoffset() is None:
        raise ValueError("Start time must include a timezone.")
    if not isinstance(end, datetime) or end.tzinfo is None or end.utcoffset() is None:
        raise ValueError("End time must include a timezone.")
    start = start.astimezone(timezone.utc)
    end = end.astimezone(timezone.utc)
    if start >= end:
        raise ValueError("Start time must be before end time.")
    if isinstance(max_candles, bool) or not isinstance(max_candles, int) or not 2 <= max_candles <= 5000:
        raise ValueError("Maximum candles must be between 2 and 5000.")
    if not isinstance(quota, ProviderQuota):
        raise ValueError("A ProviderQuota configuration is required.")
    if governor is not None and governor.quota != quota:
        raise ValueError("Planner quota must match the provider governor quota.")

    duration = timeframe_duration(timeframe)
    estimated_candles = math.floor((end - start) / duration) + 1
    window = duration * (max_candles - 1)
    requests = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + window, end)
        request = CandleRequest(pair, timeframe, max_candles, cursor, chunk_end)
        validate_request(request)
        requests.append(request)
        cursor = chunk_end + duration

    batches = tuple(
        tuple(requests[index:index + quota.max_requests])
        for index in range(0, len(requests), quota.max_requests)
    )
    windows_required = len(batches)
    quota_window_wait = max(0, windows_required - 1) * quota.window_seconds
    spacing_wait = max(0, len(requests) - 1) * quota.min_interval_seconds
    estimated_wait = max(quota_window_wait, spacing_wait)

    available_now = quota.max_requests
    can_start_now = True
    retry_after = 0.0
    if governor is not None:
        decision = governor.snapshot(now)
        available_now = decision.remaining if decision.allowed else 0
        can_start_now = decision.allowed and decision.remaining > 0
        retry_after = decision.retry_after_seconds

    return BackfillPlan(
        pair=pair,
        timeframe=timeframe,
        start=start,
        end=end,
        estimated_candles=estimated_candles,
        max_candles_per_request=max_candles,
        requests=tuple(requests),
        quota_batches=batches,
        quota_windows_required=windows_required,
        estimated_wait_seconds=estimated_wait,
        requests_available_now=available_now,
        can_start_now=can_start_now,
        retry_after_seconds=retry_after,
    )
