"""Provider-neutral requests, validation, and quality checks for market data."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from src.market_data import (
    Candle,
    CandleValidationError,
    validate_candle_series,
)

TIMEFRAME_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}


class MarketDataError(RuntimeError):
    """Base exception for market-data pipeline failures."""


class ProviderUnavailable(MarketDataError):
    """Raised when a provider cannot return usable market data."""


@dataclass(frozen=True)
class CandleRequest:
    """A bounded request for one currency pair and candle interval."""

    pair: str
    timeframe: str
    limit: int = 500


@dataclass(frozen=True)
class CandleGap:
    """A missing candle interval between two available candle timestamps."""

    previous: datetime
    missing: datetime
    following: datetime


@dataclass(frozen=True)
class DataQualityReport:
    """Summary of coverage and validity for a candle series."""

    pair: str
    timeframe: str
    received: int
    expected: int
    missing: int
    gaps: tuple[CandleGap, ...]
    coverage: float


class MarketDataProvider(Protocol):
    """Interface implemented by each external or local data provider."""

    name: str

    def fetch_candles(self, request: CandleRequest) -> Sequence[Candle]:
        """Return candles in chronological order for the supplied request."""


def validate_request(request: CandleRequest) -> CandleRequest:
    """Reject unsupported pairs, intervals, and unreasonable request sizes."""
    if not isinstance(request, CandleRequest):
        raise ValueError("A CandleRequest is required.")
    parts = request.pair.split("/")
    if len(parts) != 2 or not all(part.isalpha() for part in parts):
        raise ValueError("Currency pair must use BASE/QUOTE format.")
    if parts[0] == parts[1]:
        raise ValueError("Base and quote currencies must be different.")
    if request.timeframe not in TIMEFRAME_SECONDS:
        raise ValueError("Unsupported candle timeframe.")
    if isinstance(request.limit, bool) or not isinstance(request.limit, int):
        raise ValueError("Candle limit must be an integer.")
    if not 1 <= request.limit <= 5000:
        raise ValueError("Candle limit must be between 1 and 5000.")
    return request


def timeframe_duration(timeframe: str) -> timedelta:
    """Return the duration represented by a supported candle timeframe."""
    try:
        return timedelta(seconds=TIMEFRAME_SECONDS[timeframe])
    except KeyError as error:
        raise ValueError("Unsupported candle timeframe.") from error


def validate_provider_candles(
    request: CandleRequest,
    candles: Sequence[Candle],
) -> list[Candle]:
    """Validate provider output and enforce request pair and size constraints."""
    validate_request(request)
    if not candles:
        raise MarketDataError("Provider returned no candles.")
    if len(candles) > request.limit:
        raise MarketDataError("Provider returned more candles than requested.")
    try:
        validated = validate_candle_series(list(candles))
    except (CandleValidationError, TypeError, AttributeError) as error:
        raise MarketDataError(f"Provider returned invalid candles: {error}") from error
    if any(candle.pair != request.pair for candle in validated):
        raise MarketDataError("Provider returned candles for the wrong pair.")
    return validated


def fetch_market_data(
    provider: MarketDataProvider,
    request: CandleRequest,
) -> list[Candle]:
    """Fetch and validate provider data; fail closed when the provider errors."""
    validate_request(request)
    try:
        candles = provider.fetch_candles(request)
    except MarketDataError:
        raise
    except Exception as error:
        raise ProviderUnavailable(
            f"Market-data provider {provider.name!r} failed."
        ) from error
    return validate_provider_candles(request, candles)


def filter_closed_candles(
    candles: Sequence[Candle],
    timeframe: str,
    now: datetime | None = None,
) -> list[Candle]:
    """Remove the currently forming candle using UTC-aware clock comparison."""
    duration = timeframe_duration(timeframe)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("Current time must include a timezone.")
    current = current.astimezone(timezone.utc)
    validated = validate_candle_series(list(candles))
    return [
        candle for candle in validated
        if candle.timestamp.astimezone(timezone.utc) + duration <= current
    ]


def merge_candle_series(*series: Sequence[Candle]) -> list[Candle]:
    """Merge validated series, with later arguments replacing duplicate candles."""
    merged: dict[tuple[str, datetime], Candle] = {}
    for candles in series:
        for candle in validate_candle_series(list(candles)):
            key = (candle.pair, candle.timestamp.astimezone(timezone.utc))
            merged[key] = candle
    if not merged:
        raise CandleValidationError("No market candles were supplied.")
    pairs = {pair for pair, _ in merged}
    if len(pairs) != 1:
        raise CandleValidationError("Merged candle series must contain one pair.")
    return sorted(merged.values(), key=lambda candle: candle.timestamp)


def detect_candle_gaps(
    candles: Sequence[Candle],
    timeframe: str,
) -> tuple[CandleGap, ...]:
    """Find missing expected timestamps without fabricating replacement candles."""
    duration = timeframe_duration(timeframe)
    validated = validate_candle_series(list(candles))
    gaps = []
    for previous, following in zip(validated, validated[1:]):
        expected = previous.timestamp + duration
        while expected < following.timestamp:
            gaps.append(CandleGap(previous.timestamp, expected, following.timestamp))
            expected += duration
    return tuple(gaps)


def assess_data_quality(
    candles: Sequence[Candle],
    timeframe: str,
    expected_count: int | None = None,
) -> DataQualityReport:
    """Report observed coverage and internal gaps for a validated candle series."""
    validated = validate_candle_series(list(candles))
    if expected_count is None:
        expected_count = len(validated) + len(detect_candle_gaps(validated, timeframe))
    if (
        isinstance(expected_count, bool)
        or not isinstance(expected_count, int)
        or expected_count < len(validated)
    ):
        raise ValueError("Expected candle count must be an integer at least received.")
    gaps = detect_candle_gaps(validated, timeframe)
    missing = max(expected_count - len(validated), len(gaps))
    return DataQualityReport(
        pair=validated[0].pair,
        timeframe=timeframe,
        received=len(validated),
        expected=expected_count,
        missing=missing,
        gaps=gaps,
        coverage=len(validated) / expected_count if expected_count else 1.0,
    )


def candles_to_close_prices(candles: Sequence[Candle]) -> list[float]:
    """Convert a validated chronological series to close prices for research."""
    return [candle.close for candle in validate_candle_series(list(candles))]
