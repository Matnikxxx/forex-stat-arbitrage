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
