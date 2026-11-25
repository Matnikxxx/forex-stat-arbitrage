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
    """Fetch closed candles, merge corrections, and persist a clean history.

    Providers currently expose bounded recent-window requests rather than
    timestamp-range requests. Each sync therefore refreshes that window,
    merges it with local history, and never fabricates missing candles.
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
        """Synchronize one pair; invalid or forming-only data is not persisted."""
        fetched = fetch_market_data(self.provider, request)
        closed = filter_closed_candles(fetched, request.timeframe, now)
        if not closed:
            raise ValueError("Provider returned no fully closed candles.")

        try:
            existing = self.storage.load_candles(request.pair)
        except ValueError:
            raise

        combined = (
            merge_candle_series(existing, closed)
            if existing
            else closed
        )
        self.storage.save_candles(combined)
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
    ) -> list[Candle]:
        """Load validated historical candles from local storage."""
        return self.storage.load_candles(pair, start=start, end=end)
