# Provider health and circuit breaker

Wrap a market-data provider in `CircuitBreakingProvider` to prevent repeated
requests to a failing endpoint:

```python
from src.provider_health import CircuitBreakingProvider
from src.twelve_data import TwelveDataProvider

provider = CircuitBreakingProvider(
    TwelveDataProvider(),
    failure_threshold=3,
    reset_timeout=60,
)
health = provider.health()
```

The circuit opens after the configured number of consecutive request failures.
Calls are blocked during the cooldown. After the cooldown, one recovery probe
is allowed; success closes the circuit and failure starts a new cooldown.
Health snapshots expose counts and exception types, never raw error messages
or credentials.

This is a synchronous provider wrapper. It does not create a background
scheduler, guarantee provider uptime, or execute trades. Invalid candle data
is validated by the existing market-feed layer and is not treated as a
successful usable data response by that layer.
