# Feed freshness and coverage monitoring

Use `assess_feed_health` to create a compact health summary for a stored
candle series. It reports the latest closed candle, its age, missing candles,
coverage, and a status of `healthy`, `warning`, or `stale`.

```python
from src.data_monitoring import assess_feed_health
from src.market_storage import CandleStorage

candles = CandleStorage("data/market.db").load_candles("EUR/USD")
health = assess_feed_health(candles, "15m")
print(health.status, health.age_seconds, health.coverage)
```

The default freshness threshold is two candle intervals. Supply an explicit
`max_age` when a different threshold is appropriate. A warning indicates
history gaps or incomplete expected coverage; stale means the latest candle
exceeds the freshness threshold.

This is a read-only assessment. It does not fetch, repair, fabricate, or
delete market data and does not execute trades. The first version does not
apply Forex market-session calendars, so users should interpret stale status
carefully during weekends and market holidays.
