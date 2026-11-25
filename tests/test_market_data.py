from datetime import datetime, timedelta, timezone

import pytest

from src.market_data import (
    Candle,
    CandleValidationError,
    is_candle_stale,
    validate_candle,
    validate_candle_series,
)


BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_candle(timestamp=BASE_TIME, **changes):
    values = {
        "pair": "EUR/USD",
        "timestamp": timestamp,
        "open": 1.10,
        "high": 1.12,
        "low": 1.09,
        "close": 1.11,
        "volume": 100.0,
    }
    values.update(changes)
    return Candle(**values)


def test_valid_candle_is_accepted():
    candle = make_candle()
    assert validate_candle(candle) == candle


def test_rejects_invalid_pair():
    with pytest.raises(CandleValidationError, match="BASE/QUOTE"):
        validate_candle(make_candle(pair="EURUSD"))


def test_rejects_timestamp_without_timezone():
    naive_time = datetime(2026, 1, 1)
    with pytest.raises(CandleValidationError, match="timezone"):
        validate_candle(make_candle(timestamp=naive_time))


def test_rejects_non_finite_or_non_positive_prices():
    with pytest.raises(CandleValidationError, match="finite"):
        validate_candle(make_candle(close=float("nan")))
    with pytest.raises(CandleValidationError, match="greater than zero"):
        validate_candle(make_candle(open=0.0))


def test_rejects_inconsistent_ohlc_and_negative_volume():
    with pytest.raises(CandleValidationError, match="high"):
        validate_candle(make_candle(high=1.105))
    with pytest.raises(CandleValidationError, match="negative"):
        validate_candle(make_candle(volume=-1.0))


def test_series_must_be_non_empty_same_pair_and_chronological():
    with pytest.raises(CandleValidationError, match="No market candles"):
        validate_candle_series([])
    with pytest.raises(CandleValidationError, match="one pair"):
        validate_candle_series(
            [
                make_candle(),
                make_candle(
                    pair="GBP/USD",
                    timestamp=BASE_TIME + timedelta(minutes=1),
                ),
            ]
        )
    with pytest.raises(CandleValidationError, match="chronological"):
        validate_candle_series(
            [
                make_candle(),
                make_candle(timestamp=BASE_TIME),
            ]
        )


def test_stale_candle_detection_uses_utc_time():
    now = BASE_TIME + timedelta(minutes=6)
    assert is_candle_stale(make_candle(), now=now)
    assert not is_candle_stale(
        make_candle(), now=now, max_age=timedelta(minutes=10)
    )


def test_stale_check_rejects_naive_current_time():
    with pytest.raises(ValueError, match="timezone"):
        is_candle_stale(make_candle(), now=datetime(2026, 1, 1))
