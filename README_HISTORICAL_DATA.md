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


## Resumable backfills

Backfill progress is stored in the same SQLite database as candle history.
If a provider fails after one or more successful windows, rerun the exact same
backfill call (same pair, timeframe, date range, and candle cap). The service
continues from the first unfinished window instead of downloading completed
windows again. Progress is isolated by pair and timeframe and is removed when
the requested range completes. A different request for the same pair/timeframe
is rejected while an unfinished job exists.


## Provider quota protection

Wrap a provider with `QuotaAwareProvider` and a `ProviderRequestGovernor`
to enforce a rolling request limit and minimum spacing between calls. A blocked
request raises `ProviderQuotaExceeded`, which is a `ProviderUnavailable`
subclass so an existing provider failover chain can move to another provider.
The wrapper does not sleep or retry in the background: callers can inspect
`retry_after_seconds` and schedule a later attempt. When a provider reports a
rate-limit cooldown (for example, from a Retry-After header), call
`governor.defer(seconds)`. Quotas are configured per provider instance and
must be set to the provider's current documented limits; they do not infer or
guarantee an account's remaining remote API credits.


## Backfill preflight planning

Use `plan_backfill` before starting a large download to estimate its bounded
provider requests and group them into batches that fit the configured rolling
quota. The planner is read-only: it does not call the provider or write candles.

```python
from src.backfill_planner import plan_backfill
from src.provider_quota import ProviderQuota, ProviderRequestGovernor

quota = ProviderQuota(max_requests=8, window_seconds=60, min_interval_seconds=1)
governor = ProviderRequestGovernor(quota)
plan = plan_backfill(
    pair="EUR/USD",
    timeframe="15m",
    start=start,
    end=end,
    quota=quota,
    max_candles=1000,
    governor=governor,
)
print(plan.estimated_candles, len(plan.requests))
print(plan.quota_windows_required, plan.estimated_wait_seconds)
print(plan.can_start_now, plan.retry_after_seconds)
```

The plan reports estimated candle count, exact request windows, quota-sized
batches, currently available local request budget, and an estimated minimum
wait based on the configured rolling window and minimum spacing. These are
planning estimates: provider history limits, missing market sessions, remote
credits, and provider-specific rules can change the actual result. Configure
the quota from the provider's current terms; this feature does not discover
remote account credits or bypass rate limits.


## Quota-aware backfill execution

After creating a preflight plan, use `execute_backfill_plan` to run it through
the historical data service. The service should use a `QuotaAwareProvider`
when local request limits need enforcement:

```python
from src.backfill_execution import execute_backfill_plan
from src.backfill_planner import plan_backfill

plan = plan_backfill(
    pair="EUR/USD",
    timeframe="15m",
    start=start,
    end=end,
    quota=quota,
    governor=governor,
)
outcome = execute_backfill_plan(service, plan)
if outcome.deferred:
    print("Resume after seconds:", outcome.retry_after_seconds)
else:
    print("Stored candles:", outcome.stored_candles)
```

The executor never busy-waits. If the quota governor blocks a request, it
returns a deferred result with completed-request progress and the retry delay.
Successful earlier windows remain stored and the SQLite checkpoint allows the
same plan to resume later. Provider outages and invalid market data are not
silently converted into quota deferrals; those errors remain visible to the
caller. This remains a historical-data feature for research and paper trading,
not live order execution.
