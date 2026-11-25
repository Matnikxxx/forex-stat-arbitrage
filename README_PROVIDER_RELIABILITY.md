# Provider circuit-breaker reliability

Wrap a market-data provider with `CircuitBreakingProvider` to stop repeated
calls during a provider outage and allow one recovery probe after the cooldown.

Only availability failures count toward the circuit threshold. A
`ProviderUnavailable` error increments failure counters and can open the
circuit. Other `MarketDataError` responses, including invalid market-data
payloads, are propagated unchanged and do not trigger failover or count as
provider outages.

The wrapper protects its counters and circuit state with a lock. When the
cooldown expires, only one concurrent request can act as the half-open recovery
probe; other requests receive `ProviderUnavailable` without calling the
underlying provider.

This component only protects market-data access. It does not place trades,
repair data, or change paper-account state.
