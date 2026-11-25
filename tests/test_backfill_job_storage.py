from datetime import datetime, timedelta, timezone

import pytest

from src.backfill_job_storage import BackfillJob, BackfillJobStorage

START = datetime(2025, 1, 1, tzinfo=timezone.utc)
END = START + timedelta(days=2)


def job(pair="EUR/USD", timeframe="15m", start=START, end=END, limit=1000):
    return BackfillJob(pair, timeframe, start, end, limit)


def test_save_and_load_job(tmp_path):
    storage = BackfillJobStorage(tmp_path / "market.db")
    expected = job()
    storage.save(expected)
    assert storage.load("EUR/USD", "15m") == expected


def test_job_survives_storage_reopen(tmp_path):
    database = tmp_path / "market.db"
    expected = job()
    BackfillJobStorage(database).save(expected)
    assert BackfillJobStorage(database).load("EUR/USD", "15m") == expected


def test_save_replaces_existing_job_for_same_pair_and_timeframe(tmp_path):
    storage = BackfillJobStorage(tmp_path / "market.db")
    storage.save(job(limit=100))
    updated = job(start=START + timedelta(days=1), limit=250)
    storage.save(updated)
    assert storage.load("EUR/USD", "15m") == updated


def test_jobs_are_isolated_by_pair_and_timeframe(tmp_path):
    storage = BackfillJobStorage(tmp_path / "market.db")
    expected = [job(), job(timeframe="1h"), job(pair="GBP/USD")]
    for item in expected:
        storage.save(item)
    assert storage.load_all() == sorted(expected, key=lambda item: (item.pair, item.timeframe))


def test_load_all_is_empty_for_new_database(tmp_path):
    assert BackfillJobStorage(tmp_path / "market.db").load_all() == []


def test_timezone_values_are_normalized_to_utc(tmp_path):
    storage = BackfillJobStorage(tmp_path / "market.db")
    local_start = START.astimezone(timezone(timedelta(hours=2)))
    local_end = END.astimezone(timezone(timedelta(hours=2)))
    storage.save(job(start=local_start, end=local_end))
    assert storage.load("EUR/USD", "15m") == job()


def test_delete_reports_whether_job_existed(tmp_path):
    storage = BackfillJobStorage(tmp_path / "market.db")
    storage.save(job())
    assert storage.delete("EUR/USD", "15m") is True
    assert storage.delete("EUR/USD", "15m") is False
    assert storage.load_all() == []


@pytest.mark.parametrize("start,end", [
    (datetime(2025, 1, 1), END),
    (START, datetime(2025, 1, 3)),
    (END, START),
    (START, START),
])
def test_save_rejects_invalid_date_ranges(tmp_path, start, end):
    storage = BackfillJobStorage(tmp_path / "market.db")
    with pytest.raises(ValueError):
        storage.save(job(start=start, end=end))


@pytest.mark.parametrize("limit", [True, 0, 1, -1, 1.5, 5001])
def test_save_rejects_invalid_candle_limits(tmp_path, limit):
    storage = BackfillJobStorage(tmp_path / "market.db")
    with pytest.raises(ValueError, match="Maximum candles"):
        storage.save(job(limit=limit))


@pytest.mark.parametrize("pair,timeframe", [
    ("EURUSD", "15m"),
    ("EUR/USD", ""),
    ("EUR/USD", "invalid"),
])
def test_save_rejects_invalid_pair_or_timeframe(tmp_path, pair, timeframe):
    storage = BackfillJobStorage(tmp_path / "market.db")
    with pytest.raises(ValueError):
        storage.save(job(pair=pair, timeframe=timeframe))


def test_save_rejects_non_job_value(tmp_path):
    storage = BackfillJobStorage(tmp_path / "market.db")
    with pytest.raises(ValueError, match="BackfillJob"):
        storage.save("not a job")


@pytest.mark.parametrize("pair,timeframe", [("", "15m"), ("EUR/USD", "")])
def test_load_and_delete_validate_keys(tmp_path, pair, timeframe):
    storage = BackfillJobStorage(tmp_path / "market.db")
    with pytest.raises(ValueError):
        storage.load(pair, timeframe)
    with pytest.raises(ValueError):
        storage.delete(pair, timeframe)
