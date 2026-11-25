"""Tests for deterministic backfill retry scheduling."""

from datetime import datetime, timedelta, timezone

import pytest

from src.backfill_retry import schedule_backfill_retry

NOW = datetime(2026, 5, 1, 12, tzinfo=timezone.utc)


def test_first_attempt_uses_base_delay():
    result = schedule_backfill_retry(1, NOW)
    assert result.delay_seconds == 5
    assert result.next_attempt_at == NOW + timedelta(seconds=5)


def test_delay_doubles_for_each_attempt():
    delays = [
        schedule_backfill_retry(attempt, NOW).delay_seconds
        for attempt in range(1, 6)
    ]
    assert delays == [5, 10, 20, 40, 80]


def test_delay_is_capped_at_maximum():
    result = schedule_backfill_retry(20, NOW, base_delay_seconds=4, max_delay_seconds=30)
    assert result.delay_seconds == 30


def test_provider_retry_after_is_a_lower_bound():
    result = schedule_backfill_retry(
        1, NOW, base_delay_seconds=5, provider_retry_after_seconds=45
    )
    assert result.delay_seconds == 45
    assert result.provider_delay_seconds == 45


def test_larger_local_backoff_wins_over_short_provider_delay():
    result = schedule_backfill_retry(
        5, NOW, base_delay_seconds=5, provider_retry_after_seconds=10
    )
    assert result.delay_seconds == 80


def test_provider_delay_can_exceed_local_maximum():
    result = schedule_backfill_retry(
        10, NOW, base_delay_seconds=5, max_delay_seconds=60,
        provider_retry_after_seconds=120,
    )
    assert result.delay_seconds == 120


def test_timezone_is_normalized_to_utc():
    offset_now = datetime.fromisoformat("2026-05-01T14:00:00+02:00")
    result = schedule_backfill_retry(1, offset_now)
    assert result.next_attempt_at == NOW + timedelta(seconds=5)


@pytest.mark.parametrize("attempt", [0, -1, True, 1.5, "2"])
def test_rejects_invalid_attempt(attempt):
    with pytest.raises(ValueError, match="positive integer"):
        schedule_backfill_retry(attempt, NOW)


@pytest.mark.parametrize("now", [None, datetime(2026, 5, 1, 12)])
def test_rejects_missing_or_naive_clock(now):
    with pytest.raises(ValueError, match="timezone"):
        schedule_backfill_retry(1, now)


@pytest.mark.parametrize("value", [0, -1, True, float("inf"), float("nan"), "5"])
def test_rejects_invalid_base_delay(value):
    with pytest.raises(ValueError, match="Base delay"):
        schedule_backfill_retry(1, NOW, base_delay_seconds=value)


@pytest.mark.parametrize("value", [0, -1, True, float("inf"), float("nan"), "5"])
def test_rejects_invalid_maximum_delay(value):
    with pytest.raises(ValueError, match="Maximum delay"):
        schedule_backfill_retry(1, NOW, max_delay_seconds=value)


@pytest.mark.parametrize("value", [-1, True, float("inf"), float("nan"), "5"])
def test_rejects_invalid_provider_delay(value):
    with pytest.raises(ValueError, match="Provider retry delay"):
        schedule_backfill_retry(1, NOW, provider_retry_after_seconds=value)


def test_rejects_maximum_below_base():
    with pytest.raises(ValueError, match="at least the base"):
        schedule_backfill_retry(1, NOW, base_delay_seconds=10, max_delay_seconds=5)


def test_extremely_large_attempt_remains_capped():
    result = schedule_backfill_retry(10**100, NOW, max_delay_seconds=90)
    assert result.delay_seconds == 90
