"""Provider health tracking and a concurrency-safe circuit breaker."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock
from typing import Callable

from src.market_data import Candle
from src.market_feed import (
    CandleRequest,
    MarketDataError,
    MarketDataProvider,
    ProviderUnavailable,
)


@dataclass(frozen=True)
class ProviderHealth:
    """Safe snapshot of provider availability and recent outcomes."""

    provider: str
    state: str
    consecutive_failures: int
    total_successes: int
    total_failures: int
    last_error_type: str | None
    last_success_at: datetime | None
    retry_after_seconds: float


class CircuitBreakingProvider:
    """Temporarily stop calling an unhealthy provider after repeated failures.

    Only availability failures count toward the circuit threshold. Invalid
    market-data responses are propagated unchanged so failover cannot hide
    data-quality defects. A lock protects state and permits one recovery probe.
    """

    def __init__(
        self,
        provider: MarketDataProvider,
        failure_threshold: int = 3,
        reset_timeout: float = 60.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if not isinstance(failure_threshold, int) or isinstance(
            failure_threshold, bool
        ) or failure_threshold < 1:
            raise ValueError("Failure threshold must be a positive integer.")
        if (
            not isinstance(reset_timeout, (int, float))
            or isinstance(reset_timeout, bool)
            or reset_timeout <= 0
        ):
            raise ValueError("Reset timeout must be a positive number.")
        name = getattr(provider, "name", "")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Provider must have a non-empty name.")

        import time

        self.provider = provider
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_timeout = float(reset_timeout)
        self._clock = clock or time.monotonic
        self._lock = RLock()
        self._consecutive_failures = 0
        self._total_successes = 0
        self._total_failures = 0
        self._opened_at: float | None = None
        self._last_error_type: str | None = None
        self._last_success_at: datetime | None = None
        self._probe_in_progress = False

    def _state_unlocked(self) -> str:
        if self._opened_at is None:
            return "closed"
        if self._clock() - self._opened_at < self.reset_timeout:
            return "open"
        return "half-open"

    @property
    def state(self) -> str:
        """Return closed, open, or half-open based on the current clock."""
        with self._lock:
            return self._state_unlocked()

    def health(self) -> ProviderHealth:
        """Return a consistent provider-health snapshot without error messages."""
        with self._lock:
            state = self._state_unlocked()
            remaining = 0.0
            if state == "open" and self._opened_at is not None:
                remaining = max(
                    0.0,
                    self.reset_timeout - (self._clock() - self._opened_at),
                )
            return ProviderHealth(
                provider=self.name,
                state=state,
                consecutive_failures=self._consecutive_failures,
                total_successes=self._total_successes,
                total_failures=self._total_failures,
                last_error_type=self._last_error_type,
                last_success_at=self._last_success_at,
                retry_after_seconds=remaining,
            )

    def _record_failure(self, error: Exception, was_half_open: bool) -> None:
        with self._lock:
            self._total_failures += 1
            self._consecutive_failures += 1
            self._last_error_type = type(error).__name__
            if (
                self._consecutive_failures >= self.failure_threshold
                or was_half_open
            ):
                self._opened_at = self._clock()
            if was_half_open:
                self._probe_in_progress = False

    def fetch_candles(self, request: CandleRequest) -> Sequence[Candle]:
        """Fetch unless open; count availability failures and allow one probe."""
        with self._lock:
            state = self._state_unlocked()
            was_half_open = state == "half-open"
            if state == "open":
                raise ProviderUnavailable(
                    f"Provider {self.name!r} circuit is open; retry later."
                )
            if was_half_open:
                if self._probe_in_progress:
                    raise ProviderUnavailable(
                        f"Provider {self.name!r} recovery probe is already running."
                    )
                self._probe_in_progress = True

        try:
            candles = self.provider.fetch_candles(request)
        except ProviderUnavailable as error:
            self._record_failure(error, was_half_open)
            raise ProviderUnavailable(
                f"Provider {self.name!r} request failed."
            ) from error
        except MarketDataError:
            if was_half_open:
                with self._lock:
                    self._probe_in_progress = False
            raise
        except Exception as error:
            self._record_failure(error, was_half_open)
            raise ProviderUnavailable(
                f"Provider {self.name!r} request failed."
            ) from error

        with self._lock:
            self._total_successes += 1
            self._consecutive_failures = 0
            self._last_error_type = None
            self._last_success_at = datetime.now(timezone.utc)
            self._opened_at = None
            self._probe_in_progress = False
        return candles
