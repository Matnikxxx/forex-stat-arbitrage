"""Tests for quota-aware historical backfill planning."""

from datetime import datetime, timedelta, timezone

import pytest

from src.backfill_planner import plan_backfill
from src.provider_quota import ProviderQuota, ProviderRequestGovernor

START = datetime(2026, 1, 1, tzinfo=timezone.utc)
QUOTA = ProviderQuota(max_requests=2, window_seconds=60)


def test_plan_splits_range_into_non_overlapping_requests():
    plan = plan_backfill(
        "EUR/USD", "15m", START, START + timedelta(minutes=45),
        QUOTA, max_candles=2,
    )
    assert len(plan.requests) == 2
    assert plan.requests[0].end + timedelta(minutes=15) == plan.requests[1].start


def test_plan_uses_existing_backfill_chunk_boundaries():
    plan = plan_backfill(
        "EUR/USD", "15m", START, START + timedelta(minutes=45),
        QUOTA, max_candles=2,
    )
    assert [(r.start, r.end) for r in plan.requests] == [
        (START, START + timedelta(minutes=15)),
        (START + timedelta(minutes=30), START + timedelta(minutes=45)),
    ]
    assert plan.estimated_candles == 4
    assert plan.quota_windows_required == 1
    assert len(plan.quota_batches) == 1
    assert len(plan.quota_batches[0]) == 2


def test_plan_groups_requests_into_quota_windows():
    plan = plan_backfill(
        "EUR/USD", "15m", START, START + timedelta(minutes=75),
        ProviderQuota(max_requests=1, window_seconds=120), max_candles=2,
    )
    assert len(plan.requests) == 3
    assert [len(batch) for batch in plan.quota_batches] == [1, 1, 1]
    assert plan.quota_windows_required == 3
    assert plan.estimated_wait_seconds == 240


def test_plan_reports_current_governor_budget():
    quota = ProviderQuota(max_requests=1, window_seconds=60)
    governor = ProviderRequestGovernor(quota)
    governor.acquire(START)
    plan = plan_backfill(
        "EUR/USD", "15m", START, START + timedelta(minutes=45),
        quota, max_candles=2, governor=governor, now=START,
    )
    assert plan.requests_available_now == 0
    assert plan.can_start_now is False
    assert plan.retry_after_seconds == 60


def test_plan_without_governor_assumes_configured_window_budget():
    plan = plan_backfill(
        "EUR/USD", "15m", START, START + timedelta(minutes=15), QUOTA
    )
    assert plan.requests_available_now == 2
    assert plan.can_start_now is True
    assert plan.retry_after_seconds == 0


@pytest.mark.parametrize(
    "start,end",
    [
        (datetime(2026, 1, 1), START + timedelta(hours=1)),
        (START, datetime(2026, 1, 1, 1)),
        (START, START),
        (START + timedelta(hours=1), START),
    ],
)
def test_plan_rejects_invalid_date_ranges(start, end):
    with pytest.raises(ValueError):
        plan_backfill("EUR/USD", "15m", start, end, QUOTA)


@pytest.mark.parametrize("limit", [True, 0, 1, -1, 5001, 1.5])
def test_plan_rejects_invalid_chunk_limits(limit):
    with pytest.raises(ValueError, match="between 2 and 5000"):
        plan_backfill(
            "EUR/USD", "15m", START, START + timedelta(hours=1),
            QUOTA, max_candles=limit,
        )


def test_plan_rejects_invalid_pair_and_timeframe():
    with pytest.raises(ValueError, match="BASE/QUOTE"):
        plan_backfill(
            "EURUSD", "15m", START, START + timedelta(hours=1), QUOTA
        )
    with pytest.raises(ValueError, match="Unsupported candle timeframe"):
        plan_backfill(
            "EUR/USD", "2m", START, START + timedelta(hours=1), QUOTA
        )


def test_plan_does_not_call_provider_or_modify_storage():
    plan = plan_backfill(
        "EUR/USD", "15m", START, START + timedelta(hours=1), QUOTA
    )
    assert plan.requests


def test_plan_includes_minimum_spacing_in_wait_estimate():
    quota = ProviderQuota(
        max_requests=10, window_seconds=60, min_interval_seconds=3
    )
    plan = plan_backfill(
        "EUR/USD", "15m", START, START + timedelta(minutes=75),
        quota, max_candles=2,
    )
    assert len(plan.requests) == 3
    assert plan.estimated_wait_seconds == 6


def test_plan_rejects_governor_with_different_quota():
    governor = ProviderRequestGovernor(
        ProviderQuota(max_requests=1, window_seconds=60)
    )
    with pytest.raises(ValueError, match="must match"):
        plan_backfill(
            "EUR/USD", "15m", START, START + timedelta(minutes=15),
            QUOTA, governor=governor,
        )
