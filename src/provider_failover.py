"""Ordered provider failover with strict validation and observable outcomes."""

from dataclasses import dataclass
from typing import Sequence

from src.market_data import Candle
from src.market_feed import (
    CandleRequest,
    MarketDataProvider,
    ProviderUnavailable,
    fetch_market_data,
    validate_request,
)


@dataclass(frozen=True)
class ProviderAttempt:
    """Outcome of one provider attempt, without credentials or raw payloads."""

    provider: str
    succeeded: bool
    error_type: str | None = None


@dataclass(frozen=True)
class ProviderFetchResult:
    """Validated candles and the provider that supplied them."""

    candles: tuple[Candle, ...]
    provider: str
    attempts: tuple[ProviderAttempt, ...]


class FallbackMarketDataProvider:
    """Try providers in priority order, falling back only on availability errors.

    Invalid data is not silently accepted or masked by trying another source:
    validation failures are surfaced immediately for investigation.
    """

    def __init__(self, providers: Sequence[MarketDataProvider]) -> None:
        self.providers = tuple(providers)
        if not self.providers:
            raise ValueError("At least one market-data provider is required.")
        names = [getattr(provider, "name", "") for provider in self.providers]
        if any(not isinstance(name, str) or not name.strip() for name in names):
            raise ValueError("Every provider must have a non-empty name.")
        if len(set(names)) != len(names):
            raise ValueError("Provider names must be unique.")
        self.name = "fallback"
        self.last_result: ProviderFetchResult | None = None

    def fetch_with_report(self, request: CandleRequest) -> ProviderFetchResult:
        """Fetch from the first available provider and report tried providers."""
        validate_request(request)
        attempts = []
        for provider in self.providers:
            try:
                candles = fetch_market_data(provider, request)
            except ProviderUnavailable as error:
                attempts.append(
                    ProviderAttempt(
                        provider=provider.name,
                        succeeded=False,
                        error_type=type(error).__name__,
                    )
                )
                continue
            attempts.append(
                ProviderAttempt(provider=provider.name, succeeded=True)
            )
            result = ProviderFetchResult(
                candles=tuple(candles),
                provider=provider.name,
                attempts=tuple(attempts),
            )
            self.last_result = result
            return result

        self.last_result = None
        names = ", ".join(attempt.provider for attempt in attempts)
        raise ProviderUnavailable(
            f"All configured market-data providers are unavailable: {names}."
        )

    def fetch_candles(self, request: CandleRequest) -> list[Candle]:
        """Implement the standard provider interface."""
        return list(self.fetch_with_report(request).candles)
