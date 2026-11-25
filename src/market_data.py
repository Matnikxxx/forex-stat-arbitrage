"""Canonical market candle model and validation helpers."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math


class CandleValidationError(ValueError):
    """Raised when market data is incomplete or internally inconsistent."""


@dataclass(frozen=True)
class Candle:
    """One OHLCV candle with a timezone-aware timestamp."""

    pair: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


def validate_candle(candle: Candle) -> Candle:
    """Validate one candle and return it unchanged when it is safe to use."""
    if not candle.pair or "/" not in candle.pair:
        raise CandleValidationError("Currency pair must use BASE/QUOTE format.")
    if candle.timestamp.tzinfo is None or candle.timestamp.utcoffset() is None:
        raise CandleValidationError("Candle timestamp must include a timezone.")

    values = (candle.open, candle.high, candle.low, candle.close, candle.volume)
    if not all(math.isfinite(value) for value in values):
        raise CandleValidationError("Candle prices and volume must be finite.")
    if min(candle.open, candle.high, candle.low, candle.close) <= 0:
        raise CandleValidationError("OHLC prices must be greater than zero.")
    if candle.volume < 0:
        raise CandleValidationError("Candle volume cannot be negative.")
    if candle.high < max(candle.open, candle.close, candle.low):
        raise CandleValidationError("Candle high is below another OHLC value.")
    if candle.low > min(candle.open, candle.close, candle.high):
        raise CandleValidationError("Candle low is above another OHLC value.")
    return candle


def validate_candle_series(candles: list[Candle]) -> list[Candle]:
    """Validate candles and require unique, strictly increasing timestamps."""
    validated = [validate_candle(candle) for candle in candles]
    if not validated:
        raise CandleValidationError("No market candles were supplied.")

    pair = validated[0].pair
    previous_time = None
    for candle in validated:
        if candle.pair != pair:
            raise CandleValidationError("A candle series must contain one pair.")
        timestamp = candle.timestamp.astimezone(timezone.utc)
        if previous_time is not None and timestamp <= previous_time:
            raise CandleValidationError(
                "Candle timestamps must be unique and chronological."
            )
        previous_time = timestamp
    return validated


def is_candle_stale(
    candle: Candle,
    now: datetime | None = None,
    max_age: timedelta = timedelta(minutes=5),
) -> bool:
    """Return true when a valid candle is older than the allowed age."""
    validate_candle(candle)
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None or current_time.utcoffset() is None:
        raise ValueError("Current time must include a timezone.")
    if max_age.total_seconds() < 0:
        raise ValueError("Maximum candle age cannot be negative.")
    age = current_time.astimezone(timezone.utc) - candle.timestamp.astimezone(
        timezone.utc
    )
    return age > max_age
