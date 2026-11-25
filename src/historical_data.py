"""Safe synchronization of provider candles into local historical storage."""

from dataclasses import dataclass
from datetime import datetime, timezone

from src.market_data import Candle
from src.market_feed import (
    CandleRequest,
    DataQualityReport,
    MarketDataProvider,
    assess_data_quality,
    fetch_market_data,
    filter_closed_candles,
    merge_candle_series,
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
