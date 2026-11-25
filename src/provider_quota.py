"""Rolling-window request quotas and safe provider throttling."""

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from threading import RLock
from typing import Callable

from src.market_feed import CandleRequest, MarketDataProvider, ProviderUnavailable


@dataclass(frozen=True)
class ProviderQuota:
    """Request limits for one provider."""

    max_requests: int
    window_seconds: float
    min_interval_seconds: float = 0.0

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_requests, bool)
            or not isinstance(self.max_requests, int)
            or self.max_requests < 1
        ):
            raise ValueError("Maximum requests must be a positive integer.")
        for label, value in (
            ("Window", self.window_seconds),
            ("Minimum interval", self.min_interval_seconds),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
                or (label == "Window" and value == 0)
            ):
                raise ValueError(f"{label} seconds must be a valid positive duration.")


@dataclass(frozen=True)
class QuotaDecision:
    """Whether a provider request can proceed and when to retry."""

    allowed: bool
    remaining: int
    retry_after_seconds: float
    reset_at: datetime | None


class ProviderQuotaExceeded(ProviderUnavailable):
    """Raised before a provider call when its local quota is exhausted."""

    def __init__(self, provider_name: str, retry_after_seconds: float) -> None:
        self.retry_after_seconds = max(0.0, retry_after_seconds)
        super().__init__(
            f"Provider {provider_name!r} quota is unavailable; "
            f"retry after {self.retry_after_seconds:.2f} seconds."
        )


class ProviderRequestGovernor:
    """Thread-safe rolling-window quota and cooldown tracker."""

    def __init__(self, quota: ProviderQuota) -> None:
        self.quota = quota
        self._requests: deque[datetime] = deque()
        self._last_request: datetime | None = None
        self._cooldown_until: datetime | None = None
        self._lock = RLock()

    @staticmethod
    def _validate_now(now: datetime) -> datetime:
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Current time must include a timezone.")
        return now.astimezone(timezone.utc)

    def acquire(self, now: datetime | None = None) -> QuotaDecision:
        """Reserve one request if all quota and cooldown rules allow it."""
        current = self._validate_now(now or datetime.now(timezone.utc))
        with self._lock:
            cutoff = current - timedelta(seconds=self.quota.window_seconds)
            while self._requests and self._requests[0] <= cutoff:
                self._requests.popleft()

            waits: list[float] = []
            reset_at = None
            if self._cooldown_until is not None and current < self._cooldown_until:
                waits.append((self._cooldown_until - current).total_seconds())
            if len(self._requests) >= self.quota.max_requests:
                quota_reset = self._requests[0] + timedelta(
                    seconds=self.quota.window_seconds
                )
                waits.append((quota_reset - current).total_seconds())
                reset_at = quota_reset
            if (
                self._last_request is not None
                and self.quota.min_interval_seconds > 0
            ):
                next_allowed = self._last_request + timedelta(
                    seconds=self.quota.min_interval_seconds
                )
                if current < next_allowed:
                    waits.append((next_allowed - current).total_seconds())

            retry_after = max(waits, default=0.0)
            if retry_after > 0:
                return QuotaDecision(
                    allowed=False,
                    remaining=max(0, self.quota.max_requests - len(self._requests)),
                    retry_after_seconds=retry_after,
                    reset_at=reset_at,
                )

            self._requests.append(current)
            self._last_request = current
            return QuotaDecision(
                allowed=True,
                remaining=self.quota.max_requests - len(self._requests),
                retry_after_seconds=0.0,
                reset_at=(
                    self._requests[0] + timedelta(seconds=self.quota.window_seconds)
                    if self._requests
                    else None
                ),
            )

    def defer(self, seconds: float, now: datetime | None = None) -> datetime:
        """Apply a provider-supplied cooldown, such as an HTTP Retry-After."""
        if (
            isinstance(seconds, bool)
            or not isinstance(seconds, (int, float))
            or not math.isfinite(seconds)
            or seconds < 0
        ):
            raise ValueError("Cooldown seconds must be a finite non-negative number.")
        current = self._validate_now(now or datetime.now(timezone.utc))
        until = current + timedelta(seconds=seconds)
        with self._lock:
            if self._cooldown_until is None or until > self._cooldown_until:
                self._cooldown_until = until
            return self._cooldown_until

    def snapshot(self, now: datetime | None = None) -> QuotaDecision:
        """Inspect available quota without reserving a request."""
        current = self._validate_now(now or datetime.now(timezone.utc))
        with self._lock:
            cutoff = current - timedelta(seconds=self.quota.window_seconds)
            while self._requests and self._requests[0] <= cutoff:
                self._requests.popleft()
            waits: list[float] = []
            reset_at = None
            if self._cooldown_until is not None and current < self._cooldown_until:
                waits.append((self._cooldown_until - current).total_seconds())
            if len(self._requests) >= self.quota.max_requests:
                reset_at = self._requests[0] + timedelta(
                    seconds=self.quota.window_seconds
                )
                waits.append((reset_at - current).total_seconds())
            if self._last_request is not None and self.quota.min_interval_seconds:
                next_allowed = self._last_request + timedelta(
                    seconds=self.quota.min_interval_seconds
                )
                if current < next_allowed:
                    waits.append((next_allowed - current).total_seconds())
            retry_after = max(waits, default=0.0)
            return QuotaDecision(
                allowed=retry_after <= 0,
                remaining=max(0, self.quota.max_requests - len(self._requests)),
                retry_after_seconds=retry_after,
                reset_at=reset_at,
            )


class QuotaAwareProvider:
    """Reserve quota before delegating a market-data request."""

    def __init__(
        self,
        provider: MarketDataProvider,
        governor: ProviderRequestGovernor,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.provider = provider
        self.governor = governor
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.name = provider.name

    def fetch_candles(self, request: CandleRequest):
        decision = self.governor.acquire(self._clock())
        if not decision.allowed:
            raise ProviderQuotaExceeded(
                self.name, decision.retry_after_seconds
            )
        return self.provider.fetch_candles(request)
