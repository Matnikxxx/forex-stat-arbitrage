from datetime import datetime, timedelta, timezone

import pytest

from src.backfill_retry_manager import BackfillRetryManager
from src.backfill_retry_storage import BackfillRetryStorage


def test_first_failure_persists_first_retry(tmp_path):
    manager = BackfillRetryManager(BackfillRetryStorage(tmp_path / "market.db"))
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    schedule = manager.record_failure("EUR/USD", "15m", now)
    saved = manager.get_schedule("EUR/USD", "15m")
    assert schedule.attempt == 1
    assert schedule.delay_seconds == 5
    assert saved is not None
    assert saved.next_attempt_at == now + timedelta(seconds=5)


def test_repeated_failures_increment_attempt_and_backoff(tmp_path):
    manager = BackfillRetryManager(
        BackfillRetryStorage(tmp_path / "market.db"),
        base_delay_seconds=4,
        max_delay_seconds=20,
    )
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    first = manager.record_failure("EUR/USD", "15m", now)
    second = manager.record_failure("EUR/USD", "15m", now)
    third = manager.record_failure("EUR/USD", "15m", now)
    assert [first.attempt, second.attempt, third.attempt] == [1, 2, 3]
    assert [first.delay_seconds, second.delay_seconds, third.delay_seconds] == [4, 8, 16]


def test_retry_after_is_preserved_on_failure(tmp_path):
    manager = BackfillRetryManager(BackfillRetryStorage(tmp_path / "market.db"))
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    schedule = manager.record_failure(
        "EUR/USD", "15m", now, provider_retry_after_seconds=900
    )
    assert schedule.delay_seconds == 900
    assert manager.get_schedule("EUR/USD", "15m").provider_delay_seconds == 900


def test_due_retries_excludes_future_and_returns_persisted_records(tmp_path):
    database = tmp_path / "market.db"
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    manager = BackfillRetryManager(BackfillRetryStorage(database))
    manager.record_failure("EUR/USD", "15m", now)
    manager.record_failure("GBP/USD", "1h", now)
    reopened = BackfillRetryManager(BackfillRetryStorage(database))
    assert reopened.due_retries(now + timedelta(seconds=5))
    assert reopened.due_retries(now + timedelta(seconds=5))[0].pair == "EUR/USD"


def test_mark_completed_removes_retry_record(tmp_path):
    manager = BackfillRetryManager(BackfillRetryStorage(tmp_path / "market.db"))
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    manager.record_failure("EUR/USD", "15m", now)
    assert manager.mark_completed("EUR/USD", "15m") is True
    assert manager.get_schedule("EUR/USD", "15m") is None
    assert manager.mark_completed("EUR/USD", "15m") is False


def test_retry_attempts_are_isolated_by_pair_and_timeframe(tmp_path):
    manager = BackfillRetryManager(BackfillRetryStorage(tmp_path / "market.db"))
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    manager.record_failure("EUR/USD", "15m", now)
    manager.record_failure("EUR/USD", "1h", now)
    manager.record_failure("EUR/USD", "15m", now)
    assert manager.get_schedule("EUR/USD", "15m").attempt == 2
    assert manager.get_schedule("EUR/USD", "1h").attempt == 1


def test_invalid_provider_retry_after_does_not_overwrite_existing_schedule(tmp_path):
    manager = BackfillRetryManager(BackfillRetryStorage(tmp_path / "market.db"))
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    original = manager.record_failure("EUR/USD", "15m", now)
    with pytest.raises(ValueError):
        manager.record_failure("EUR/USD", "15m", now, provider_retry_after_seconds=-1)
    assert manager.get_schedule("EUR/USD", "15m").attempt == original.attempt


def test_invalid_storage_is_rejected():
    with pytest.raises(ValueError, match="BackfillRetryStorage"):
        BackfillRetryManager(None)


@pytest.mark.parametrize("base,maximum", [(0, 10), (10, 5), (float("inf"), 20)])
def test_invalid_backoff_configuration_is_rejected(tmp_path, base, maximum):
    storage = BackfillRetryStorage(tmp_path / "market.db")
    with pytest.raises(ValueError):
        BackfillRetryManager(storage, base_delay_seconds=base, max_delay_seconds=maximum)
