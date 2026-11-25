"""Safe synchronization of provider candles into local historical storage."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from src.market_data import Candle
from src.market_feed import (
    CandleRequest,
    DataQualityReport,
    MarketDataProvider,
    assess_data_quality,
    fetch_market_data,
    filter_closed_candles,
    merge_candle_series,
    timeframe_duration,
)
from src.market_storage import CandleStorage


@dataclass(frozen=True)
class HistoricalSyncResult:
    """Outcome of one validated historical-data synchronization."""

    pair: str
    timeframe: str
    fetched_count: int
    accepted_count: int
    stored_count: int
    latest_timestamp: datetime
    quality: DataQualityReport


@dataclass(frozen=True)
class HistoricalBackfillResult:
    """Summary of a multi-request historical backfill operation."""

    pair: str
    timeframe: str
    request_count: int
    fetched_count: int
    accepted_count: int
    stored_count: int
    chunks: tuple[HistoricalSyncResult, ...]


class HistoricalDataService:
    """Fetch closed candles and persist history in isolated timeframe partitions.

    Legacy records stored before timeframe support are imported into the first
    requested timeframe on sync. New records never mix different intervals.
    """

    def __init__(
        self,
        provider: MarketDataProvider,
        storage: CandleStorage,
    ) -> None:
        self.provider = provider
        self.storage = storage

    def sync(
        self,
        request: CandleRequest,
        now: datetime | None = None,
    ) -> HistoricalSyncResult:
        """Synchronize one pair/timeframe without mixing other intervals."""
        fetched = fetch_market_data(self.provider, request)
        closed = filter_closed_candles(fetched, request.timeframe, now)
        if not closed:
            raise ValueError("Provider returned no fully closed candles.")

        existing = self.storage.load_candles(
            request.pair, timeframe=request.timeframe
        )
        legacy = self.storage.load_candles(
            request.pair, timeframe="unknown"
        )
        sources = [legacy, existing, closed]
        non_empty = [series for series in sources if series]
        combined = (
            merge_candle_series(*non_empty)
            if len(non_empty) > 1
            else non_empty[0]
        )
        self.storage.save_candles(combined, timeframe=request.timeframe)
        if legacy:
            self.storage.delete_timeframe(request.pair, "unknown")
        quality = assess_data_quality(combined, request.timeframe)

        return HistoricalSyncResult(
            pair=request.pair,
            timeframe=request.timeframe,
            fetched_count=len(fetched),
            accepted_count=len(closed),
            stored_count=len(combined),
            latest_timestamp=combined[-1].timestamp,
            quality=quality,
        )

    def backfill(
        self,
        pair: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        now: datetime | None = None,
        max_candles: int = 5000,
    ) -> HistoricalBackfillResult:
        """Download a date range in bounded, non-overlapping candle windows.

        Each successful chunk is stored immediately. If a later provider call
        fails, earlier chunks remain safely available and the exception is
        propagated so callers can retry the unfinished range.
        """
        for label, value in (("Start", start), ("End", end)):
            if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{label} time must include a timezone.")
        start = start.astimezone(timezone.utc)
        end = end.astimezone(timezone.utc)
        if start >= end:
            raise ValueError("Start time must be before end time.")
        if (
            isinstance(max_candles, bool)
            or not isinstance(max_candles, int)
            or not 2 <= max_candles <= 5000
        ):
            raise ValueError("Maximum candles must be between 2 and 5000.")

        duration = timeframe_duration(timeframe)
        window = duration * (max_candles - 1)
        checkpoint = self.storage.load_backfill_checkpoint(pair, timeframe)
        if checkpoint is not None:
            saved_start, saved_end, cursor, saved_limit = checkpoint
            if (
                saved_start != start
                or saved_end != end
                or saved_limit != max_candles
            ):
                raise ValueError(
                    "An unfinished backfill exists with different parameters."
                )
        else:
            cursor = start

        chunks: list[HistoricalSyncResult] = []
        while cursor <= end:
            chunk_end = min(cursor + window, end)
            request = CandleRequest(
                pair=pair,
                timeframe=timeframe,
                limit=max_candles,
                start=cursor,
                end=chunk_end,
            )
            chunks.append(self.sync(request, now))
            cursor = chunk_end + duration
            if cursor <= end:
                self.storage.save_backfill_checkpoint(
                    pair, timeframe, start, end, cursor, max_candles
                )

        self.storage.delete_backfill_checkpoint(pair, timeframe)
        stored = (
            chunks[-1].stored_count
            if chunks
            else len(self.storage.load_candles(pair, timeframe=timeframe))
        )
        return HistoricalBackfillResult(
            pair=pair,
            timeframe=timeframe,
            request_count=len(chunks),
            fetched_count=sum(item.fetched_count for item in chunks),
            accepted_count=sum(item.accepted_count for item in chunks),
            stored_count=stored,
            chunks=tuple(chunks),
        )

    def load_history(
        self,
        pair: str,
        start: datetime | None = None,
        end: datetime | None = None,
        timeframe: str | None = None,
    ) -> list[Candle]:
        """Load local history; specify timeframe to avoid mixed intervals."""
        return self.storage.load_candles(
            pair, start=start, end=end, timeframe=timeframe
        )
