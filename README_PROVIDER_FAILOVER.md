# Provider failover

The provider failover wrapper accepts an ordered list of implementations of
`MarketDataProvider`. The first provider is primary; subsequent providers are
tried only when an earlier provider is unavailable.

```python
from src.provider_failover import FallbackMarketDataProvider
from src.twelve_data import TwelveDataProvider

provider = FallbackMarketDataProvider([
    TwelveDataProvider(),
    # Add another independently configured MarketDataProvider here.
])
```

Call `fetch_candles(request)` wherever the existing provider interface is
expected. For diagnostics, call `fetch_with_report(request)`; the result
identifies the successful provider and records which providers were tried.
Reports contain provider names and exception types only, never raw messages,
API keys, or response payloads.

## Safety rules

- Provider order is explicit and deterministic.
- Only availability failures trigger fallback.
- Malformed, mismatched, or otherwise invalid candles stop the request; they
  are not hidden by switching providers.
- If every provider is unavailable, the wrapper raises
  `ProviderUnavailable`. The historical service therefore does not store
  fabricated data or replace existing history.
- No stale local candle is returned as if it were fresh.
- This is a market-data mechanism only; it cannot execute orders.

A secondary provider must be implemented and tested separately before it is
added to the chain. Do not list a provider as active until its endpoint,
instrument coverage, timestamps, and free-tier access have been verified.
