from datetime import datetime, timedelta, timezone

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
        "EUR/USD",
        candles[0].timestamp,
        1.10,
        1.14,
        1.09,
        1.13,
        150.0,
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
        "EUR/USD",
        start=candles[1].timestamp,
        end=candles[1].timestamp,
    )
    assert result == [candles[1]]


def test_storage_rejects_invalid_candle_series(tmp_path):
    storage = CandleStorage(tmp_path / "market.db")
    invalid = make_candles()[0]
    invalid = Candle(
        invalid.pair,
        invalid.timestamp,
        invalid.open,
        invalid.low,
        invalid.low,
        invalid.close,
        invalid.volume,
    )

    with pytest.raises(CandleValidationError):
        storage.save_candles([invalid])


def test_load_rejects_naive_time_filter(tmp_path):
    storage = CandleStorage(tmp_path / "market.db")
    with pytest.raises(ValueError, match="timezone"):
        storage.load_candles("EUR/USD", start=datetime(2026, 1, 1))
