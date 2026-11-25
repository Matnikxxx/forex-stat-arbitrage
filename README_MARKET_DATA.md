# Market data foundation

## Canonical candle format

All providers convert responses into `src.market_data.Candle` before prices
enter research or paper trading. A candle contains a BASE/QUOTE currency pair,
a timezone-aware timestamp, and open, high, low, close and volume values.

Validation rejects malformed pairs, naive timestamps, non-finite or
non-positive prices, negative volume, inconsistent OHLC values, mixed-pair
series, duplicate timestamps and out-of-order candles.

## Local historical storage

`CandleStorage` stores validated candles in SQLite using a composite key:
currency pair, timeframe, and UTC timestamp. This prevents candles from
different intervals from overwriting each other. Specify the timeframe when
saving and loading data:

```python
storage.save_candles(candles, timeframe="15m")
history = storage.load_candles("EUR/USD", timeframe="15m")
```

Existing databases are migrated automatically and their old rows are retained
in an `unknown` timeframe partition until the historical service imports them
into a selected interval. Loads without a timeframe remain available for
backwards compatibility, but strategy and research code should always specify
one.

This layer only validates and stores historical prices. It does not place
orders or connect to a broker.
