# Twelve Data Provider

The Phase 66 adapter implements the provider-neutral `MarketDataProvider`
interface using the Twelve Data `/time_series` REST endpoint.

## Setup

1. Create an API key through the [Twelve Data account page](https://twelvedata.com/pricing).
2. Store it as an environment variable named `TWELVE_DATA_API_KEY`.
3. Never commit the key or paste it into source code.

Windows PowerShell (current terminal only):

```powershell
$env:TWELVE_DATA_API_KEY = "your-key"
```

GitHub Codespaces: add `TWELVE_DATA_API_KEY` under repository Codespaces
secrets, then restart the Codespace.

## Use

```python
from src.historical_data import HistoricalDataService
from src.market_feed import CandleRequest
from src.market_storage import CandleStorage
from src.twelve_data import TwelveDataProvider

provider = TwelveDataProvider()
service = HistoricalDataService(provider, CandleStorage("data/market.db"))
result = service.sync(CandleRequest("EUR/USD", "15m", limit=500))
print(result.quality)
```

The adapter requests UTC timestamps and ascending order, maps the project's
timeframes to Twelve Data interval names, and returns validated-shape candles
for the common market-feed validator. The HTTP API key is sent in the
Authorization header, not in the URL.

## Reliability and credit protection

- Only the selected pair is requested; this adapter does not fan out requests.
- Network errors and HTTP 429/5xx receive bounded exponential retries.
- Authentication and other client errors are not retried.
- JSON API rate-limit errors are surfaced immediately.
- Request timeout and retry count are configurable.
- The adapter does not poll continuously or hide API credit usage.
- A provider failure propagates to the historical service, which leaves
  previously stored candles untouched.

Twelve Data counts API credits per minute; its Basic plan also has a daily
credit cap. Check your account's current quota and Forex instrument access
before running repeated requests. Free-tier access and available history can
change, so the project does not assume a fixed quota.

This provider is for historical market data and paper-trading research only.
It has no broker integration and cannot place live orders.


## Date-range requests

Requests may optionally include timezone-aware `start` and `end` datetimes:

```python
from datetime import datetime, timezone
from src.market_feed import CandleRequest

request = CandleRequest(
    "EUR/USD", "15m", limit=5000,
    start=datetime(2025, 1, 1, tzinfo=timezone.utc),
    end=datetime(2025, 2, 1, tzinfo=timezone.utc),
)
result = service.sync(request)
```

The adapter passes these boundaries to Twelve Data as UTC `start_date` and `end_date` parameters. The existing maximum request size of 5,000 candles still applies; larger historical ranges must be split into bounded requests. Provider output outside the requested range is rejected rather than silently stored. Date-range support does not bypass account history, symbol, or credit limits.
