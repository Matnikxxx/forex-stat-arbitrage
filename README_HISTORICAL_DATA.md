# Historical Market Data Service

Phase 65 connects the provider-neutral market feed to SQLite candle storage.

## Synchronize history

```python
from datetime import datetime, timezone

from src.historical_data import HistoricalDataService
from src.market_feed import CandleRequest
from src.market_storage import CandleStorage

service = HistoricalDataService(provider, CandleStorage("data/market.db"))
result = service.sync(
    CandleRequest("EUR/USD", "15m", limit=500),
    now=datetime.now(timezone.utc),
)
print(result.quality.coverage, result.quality.gaps)
```

The provider must implement the `MarketDataProvider` interface from
`src.market_feed`. The service validates provider output, excludes candles
that have not fully closed, merges refreshed candles with stored history,
and saves the result. A later provider response replaces a candle with the
same pair and timestamp, allowing provider corrections without duplicates.

## Safety and current limitations

- A provider outage or invalid response does not overwrite stored history.
- Forming candles are never saved.
- Missing intervals are reported; the service never invents candles.
- The current provider request interface fetches a bounded recent window. It
  does not yet request arbitrary date ranges, so this phase refreshes that
  window and merges it with all locally stored history.
- No API provider, key, broker connection, or real-money execution is added.
- This remains a paper-trading research system.
