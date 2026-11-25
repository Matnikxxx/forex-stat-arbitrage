# Market data foundation

## Canonical candle format

All providers must convert their responses into `src.market_data.Candle` before
those prices can enter the research or paper-trading system. A candle contains:

- Currency pair in `BASE/QUOTE` format.
- A timezone-aware timestamp (stored in UTC).
- Open, high, low, close and volume values.

Validation rejects missing or malformed pairs, timezone-naive timestamps,
non-finite or non-positive prices, negative volume, inconsistent OHLC values,
mixed-pair series, duplicate timestamps and out-of-order candles.

Use `is_candle_stale` to prevent old prices from being treated as current. The
initial default freshness limit is five minutes; later provider/timeframe work
must choose an appropriate limit for the selected candle interval.

## Local historical storage

`src.market_storage.CandleStorage` stores validated candles in SQLite. The
primary key is the currency pair and UTC timestamp, so re-fetching a candle
updates that record instead of creating a duplicate. Queries return candles
in chronological order and can be limited to a time range.

This phase does not connect to a market-data provider or open trades. Provider
adapters, gap detection by timeframe, and provider-specific freshness rules are
separate follow-up work.