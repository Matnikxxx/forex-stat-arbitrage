from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

from src.market_data import Candle, CandleValidationError
from src.market_storage import CandleStorage


def make_candles():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        Candle("EUR/USD", start, 1.10, 1.12, 1.09, 1.11, 100.0),
        Candle(
            "EUR/USD",
            start + timedelta(minutes=15),
            1.11,
            1.13,
            1.10,
            1.12,
            120.0,
        ),
    ]


def test_saves_and_loads_candles_in_time_order(tmp_path):
    storage = CandleStorage(tmp_path / "market.db")
    candles = make_candles()
    assert storage.save_candles(candles) == 2
    loaded = storage.load_candles("EUR/USD")
    assert loaded == candles
    assert loaded[0].timestamp < loaded[1].timestamp


def test_repeated_save_updates_existing_candle(tmp_path):
    storage = CandleStorage(tmp_path / "market.db")
    candles = make_candles()
    storage.save_candles(candles)
    updated = Candle(
        "EUR/USD", candles[0].timestamp, 1.10, 1.14, 1.09, 1.13, 150.0
    )
    assert storage.save_candles([updated]) == 1
    loaded = storage.load_candles("EUR/USD")
    assert len(loaded) == 2
    assert loaded[0] == updated


def test_load_can_filter_by_time_range(tmp_path):
    storage = CandleStorage(tmp_path / "market.db")
    candles = make_candles()
    storage.save_candles(candles)
    result = storage.load_candles(
        "EUR/USD", start=candles[1].timestamp, end=candles[1].timestamp
    )
    assert result == [candles[1]]


def test_storage_rejects_invalid_candle_series(tmp_path):
    storage = CandleStorage(tmp_path / "market.db")
    invalid = make_candles()[0]
    invalid = Candle(
        invalid.pair, invalid.timestamp, invalid.open, invalid.low,
        invalid.low, invalid.close, invalid.volume,
    )
    with pytest.raises(CandleValidationError):
        storage.save_candles([invalid])


def test_load_rejects_naive_time_filter(tmp_path):
    storage = CandleStorage(tmp_path / "market.db")
    with pytest.raises(ValueError, match="timezone"):
        storage.load_candles("EUR/USD", start=datetime(2026, 1, 1))


def test_same_pair_and_timestamp_can_exist_in_two_timeframes(tmp_path):
    storage = CandleStorage(tmp_path / "market.db")
    candle = make_candles()[0]
    storage.save_candles([candle], timeframe="15m")
    hourly = Candle(
        candle.pair, candle.timestamp, 1.0, 1.3, 0.8, 1.2, 500.0
    )
    storage.save_candles([hourly], timeframe="1h")
    assert storage.load_candles("EUR/USD", timeframe="15m") == [candle]
    assert storage.load_candles("EUR/USD", timeframe="1h") == [hourly]
    assert len(storage.load_candles("EUR/USD")) == 2


def test_saving_correction_only_updates_its_timeframe(tmp_path):
    storage = CandleStorage(tmp_path / "market.db")
    candle = make_candles()[0]
    hourly = Candle(
        candle.pair, candle.timestamp, 1.0, 1.3, 0.8, 1.2, 500.0
    )
    storage.save_candles([candle], timeframe="15m")
    storage.save_candles([hourly], timeframe="1h")
    corrected = Candle(
        candle.pair, candle.timestamp, 1.0, 1.25, 0.9, 1.2, 110.0
    )
    storage.save_candles([corrected], timeframe="15m")
    assert storage.load_candles("EUR/USD", timeframe="15m") == [corrected]
    assert storage.load_candles("EUR/USD", timeframe="1h") == [hourly]


def test_existing_database_is_migrated_without_losing_rows(tmp_path):
    database = tmp_path / "legacy.db"
    candle = make_candles()[0]
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE candles (
                pair TEXT NOT NULL, timestamp TEXT NOT NULL,
                open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL,
                close REAL NOT NULL, volume REAL NOT NULL,
                PRIMARY KEY (pair, timestamp)
            )
            """
        )
        connection.execute(
            "INSERT INTO candles VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                candle.pair, candle.timestamp.isoformat(), candle.open,
                candle.high, candle.low, candle.close, candle.volume,
            ),
        )
    storage = CandleStorage(database)
    assert storage.load_candles("EUR/USD", timeframe="unknown") == [candle]
    migrated = Candle(
        candle.pair, candle.timestamp, 1.0, 1.3, 0.8, 1.2, 500.0
    )
    storage.save_candles([migrated], timeframe="1h")
    assert storage.load_candles("EUR/USD", timeframe="unknown") == [candle]
    assert storage.load_candles("EUR/USD", timeframe="1h") == [migrated]


def test_invalid_timeframe_filter_is_rejected(tmp_path):
    storage = CandleStorage(tmp_path / "market.db")
    with pytest.raises(ValueError, match="Timeframe"):
        storage.load_candles("EUR/USD", timeframe="")


def test_start_after_end_is_rejected(tmp_path):
    storage = CandleStorage(tmp_path / "market.db")
    start = datetime(2026, 1, 2, tzinfo=timezone.utc)
    end = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="after"):
        storage.load_candles("EUR/USD", start=start, end=end)


def test_delete_timeframe_only_removes_selected_partition(tmp_path):
    storage = CandleStorage(tmp_path / "market.db")
    candle = make_candles()[0]
    storage.save_candles([candle], timeframe="15m")
    storage.save_candles([candle], timeframe="1h")
    assert storage.delete_timeframe("EUR/USD", "15m") == 1
    assert storage.load_candles("EUR/USD", timeframe="15m") == []
    assert storage.load_candles("EUR/USD", timeframe="1h") == [candle]
