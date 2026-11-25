# Provider-neutral market-data pipeline

This phase adds a provider interface without locking the project to one vendor.
Every provider must implement `fetch_candles(CandleRequest)` and return the
canonical `src.market_data.Candle` model. The pipeline validates the request,
provider output, pair identity, candle count, chronological order, timestamps,
and OHLC values before data can reach research code.

Supported intervals are 1m, 5m, 15m, 30m, 1h, 4h, and 1d. Requests are capped
at 5,000 candles. The current implementation deliberately does not make
network calls or require an API key; a vendor-specific adapter can be added
without changing the strategy or backtesting modules.

The pipeline also:
- excludes an unfinished candle using a timezone-aware clock;
- merges overlapping downloads with later batches taking precedence;
- detects missing intervals instead of inventing replacement prices;
- reports received/expected coverage and missing candles; and
- converts validated candles into close-price series for statistical research.

Provider failures are surfaced as `ProviderUnavailable`. Callers should stop
opening new simulated positions when fresh validated data is unavailable.
This module does not place broker orders and does not enable live trading.
