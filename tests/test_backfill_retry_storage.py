from datetime import datetime, timedelta, timezone

import pytest

from src.backfill_retry_storage import BackfillRetryState, BackfillRetryStorage


def make_state(pair="EUR/USD", timeframe="15m", attempt=2, offset=30):
    return BackfillRetryState(
        pair=pair,
        timeframe=timeframe,
        attempt=attempt,
        next_attempt_at=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=offset),
        delay_seconds=10.0,
        provider_delay_seconds=5.0,
    )


def test_save_and_load_retry_state(tmp_path):
    storage = BackfillRetryStorage(tmp_path / "market.db")
    state = make_state()
    storage.save(state)
    assert storage.load("EUR/USD", "15m") == state


def test_retry_state_survives_storage_reopen(tmp_path):
    database = tmp_path / "market.db"
    state = make_state()
    BackfillRetryStorage(database).save(state)
    assert BackfillRetryStorage(database).load("EUR/USD", "15m") == state


def test_save_replaces_existing_pair_timeframe_schedule(tmp_path):
    storage = BackfillRetryStorage(tmp_path / "market.db")
    storage.save(make_state(attempt=1))
    updated = make_state(attempt=3, offset=90)
    storage.save(updated)
    assert storage.load("EUR/USD", "15m") == updated


def test_retry_schedules_are_isolated_by_pair_and_timeframe(tmp_path):
    storage = BackfillRetryStorage(tmp_path / "market.db")
    states = [make_state(), make_state(timeframe="1h"), make_state(pair="GBP/USD")]
    for state in states:
        storage.save(state)
    assert storage.load("EUR/USD", "15m") == states[0]
    assert storage.load("EUR/USD", "1h") == states[1]
    assert storage.load("GBP/USD", "15m") == states[2]


def test_load_due_returns_only_due_schedules_in_order(tmp_path):
    storage = BackfillRetryStorage(tmp_path / "market.db")
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    later = make_state(pair="GBP/USD", offset=20)
    first = make_state(pair="AUD/USD", offset=10)
    not_due = make_state(pair="USD/JPY", offset=60)
    for state in (not_due, later, first):
        storage.save(state)
    assert storage.load_due(now + timedelta(seconds=20)) == [first, later]


def test_load_due_accepts_timezone_equivalent_now(tmp_path):
    storage = BackfillRetryStorage(tmp_path / "market.db")
    state = make_state(offset=10)
    storage.save(state)
    local = datetime(2026, 1, 1, 2, 0, 10, tzinfo=timezone(timedelta(hours=2)))
    assert storage.load_due(local) == [state]


def test_delete_reports_presence(tmp_path):
    storage = BackfillRetryStorage(tmp_path / "market.db")
    storage.save(make_state())
    assert storage.delete("EUR/USD", "15m") is True
    assert storage.delete("EUR/USD", "15m") is False
    assert storage.load("EUR/USD", "15m") is None


@pytest.mark.parametrize("attempt", [0, -1, True, 1.5])
def test_save_rejects_invalid_attempt(tmp_path, attempt):
    storage = BackfillRetryStorage(tmp_path / "market.db")
    state = make_state()
    invalid = BackfillRetryState(state.pair, state.timeframe, attempt, state.next_attempt_at, state.delay_seconds, state.provider_delay_seconds)
    with pytest.raises(ValueError, match="Attempt"):
        storage.save(invalid)


def test_save_rejects_naive_retry_time(tmp_path):
    storage = BackfillRetryStorage(tmp_path / "market.db")
    state = make_state()
    invalid = BackfillRetryState(state.pair, state.timeframe, state.attempt, datetime(2026, 1, 1), state.delay_seconds, state.provider_delay_seconds)
    with pytest.raises(ValueError, match="timezone"):
        storage.save(invalid)


@pytest.mark.parametrize("delay,provider_delay", [(0, 0), (-1, 0), (float("inf"), 0), (1, -1), (1, float("nan"))])
def test_save_rejects_invalid_delays(tmp_path, delay, provider_delay):
    storage = BackfillRetryStorage(tmp_path / "market.db")
    state = make_state()
    invalid = BackfillRetryState(state.pair, state.timeframe, state.attempt, state.next_attempt_at, delay, provider_delay)
    with pytest.raises(ValueError):
        storage.save(invalid)


def test_invalid_pair_and_timeframe_are_rejected(tmp_path):
    storage = BackfillRetryStorage(tmp_path / "market.db")
    with pytest.raises(ValueError, match="BASE/QUOTE"):
        storage.load("EURUSD", "15m")
    with pytest.raises(ValueError, match="Timeframe"):
        storage.delete("EUR/USD", "")
