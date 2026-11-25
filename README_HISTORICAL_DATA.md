# Timeframe-aware historical candle storage

SQLite now stores each candle using a composite key of currency pair,
timeframe, and UTC timestamp. The same pair and timestamp can therefore hold
separate 15-minute and 1-hour candles without overwriting either record.

## Save and load

```python
storage.save_candles(candles, timeframe="15m")
history = storage.load_candles("EUR/USD", timeframe="15m")
```

The timeframe argument on save defaults to `"unknown"` for backwards
compatibility with older callers. Loads without a timeframe return all
partitions; strategy and research code should always select the exact
timeframe.

Existing databases are migrated automatically. Pre-existing rows are placed
in an `unknown` partition and preserved. On the first historical sync for a
pair, those legacy rows are merged into the requested timeframe and the
legacy partition is removed for that pair.

Historical synchronization keeps each interval isolated, applies provider
corrections only within the matching interval, and reports gaps using that
interval's duration. This does not add live execution or real-money trading.


## Multi-window historical backfill

Use `HistoricalDataService.backfill` to download a longer UTC date range in
sequential, non-overlapping windows. Each request is capped at 5,000 candles
(or a smaller caller-selected cap):

```python
from datetime import datetime, timezone

result = service.backfill(
    pair="EUR/USD",
    timeframe="15m",
    start=datetime(2025, 1, 1, tzinfo=timezone.utc),
    end=datetime(2025, 3, 1, tzinfo=timezone.utc),
)
print(result.request_count, result.stored_count)
```

Each successful window is saved immediately. If a later request fails, earlier
windows remain stored and the error is raised; rerun the same range to safely
fill it again. Duplicate timestamps are updated rather than duplicated. The
service does not invent candles for weekends, holidays, provider omissions, or
rate-limited requests. A successful response is not proof that the provider
has supplied every historical candle; inspect the returned coverage and gap
reports. Provider quotas and account history limits still apply.
