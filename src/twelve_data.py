"""Twelve Data REST adapter for validated Forex candle history."""

import json
import math
import os
import time
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from src.market_data import Candle
from src.market_feed import (
    CandleRequest,
    MarketDataError,
    ProviderUnavailable,
    validate_request,
)

BASE_URL = "https://api.twelvedata.com/time_series"
INTERVALS = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1h",
    "4h": "4h",
    "1d": "1day",
}


class TwelveDataRateLimitError(ProviderUnavailable):
    """Raised when Twelve Data reports a temporary API credit limit."""


class TwelveDataProvider:
    """Fetch Forex candles from Twelve Data without exposing API credentials.

    The API key is read from TWELVE_DATA_API_KEY unless passed explicitly.
    Retry behaviour is deliberately bounded to avoid exhausting free credits.
    """

    name = "twelve_data"

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = 10.0,
        max_retries: int = 2,
        retry_delay: float = 1.0,
    ) -> None:
        self.api_key = (api_key or os.getenv("TWELVE_DATA_API_KEY", "")).strip()
        if not self.api_key:
            raise ValueError("Set TWELVE_DATA_API_KEY before using this provider.")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Request timeout must be positive and finite.")
        if (
            isinstance(max_retries, bool)
            or not isinstance(max_retries, int)
            or max_retries < 0
        ):
            raise ValueError("Maximum retries must be a non-negative integer.")
        if not math.isfinite(retry_delay) or retry_delay < 0:
            raise ValueError("Retry delay must be non-negative and finite.")
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    def _build_request(self, request: CandleRequest) -> Request:
        validate_request(request)
        parameters = {
            "symbol": request.pair,
            "interval": INTERVALS[request.timeframe],
            "outputsize": request.limit,
            "timezone": "UTC",
            "order": "ASC",
        }
        if request.start is not None:
            parameters["start_date"] = request.start.astimezone(timezone.utc).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        if request.end is not None:
            parameters["end_date"] = request.end.astimezone(timezone.utc).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        params = urlencode(parameters)
        return Request(
            f"{BASE_URL}?{params}",
            headers={
                "Authorization": f"apikey {self.api_key}",
                "Accept": "application/json",
                "User-Agent": "forex-stat-arbitrage-paper/1.0",
            },
            method="GET",
        )

    @staticmethod
    def _decode_payload(raw: bytes) -> dict[str, Any]:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise MarketDataError("Twelve Data returned invalid JSON.") from error
        if not isinstance(payload, dict):
            raise MarketDataError("Twelve Data returned an unexpected response.")
        return payload

    @staticmethod
    def _raise_api_error(payload: dict[str, Any]) -> None:
        if payload.get("status") != "error" and "code" not in payload:
            return
        message = str(payload.get("message", "Twelve Data API request failed."))
        code = payload.get("code")
        if str(code) == "429":
            raise TwelveDataRateLimitError("Twelve Data API credit limit reached.")
        if str(code) in {"401", "403"}:
            raise MarketDataError("Twelve Data rejected the API key or permissions.")
        raise MarketDataError(f"Twelve Data API error: {message}")

    def _request_payload(self, api_request: Request) -> dict[str, Any]:
        attempts = self.max_retries + 1
        for attempt in range(attempts):
            try:
                with urlopen(api_request, timeout=self.timeout) as response:
                    payload = self._decode_payload(response.read())
                self._raise_api_error(payload)
                return payload
            except HTTPError as error:
                retryable = error.code == 429 or 500 <= error.code < 600
                if not retryable:
                    if error.code in {401, 403}:
                        raise MarketDataError(
                            "Twelve Data rejected the API key or permissions."
                        ) from error
                    raise MarketDataError(
                        f"Twelve Data returned HTTP {error.code}."
                    ) from error
                if attempt + 1 >= attempts:
                    if error.code == 429:
                        raise TwelveDataRateLimitError(
                            "Twelve Data API credit limit reached."
                        ) from error
                    raise ProviderUnavailable(
                        f"Twelve Data temporary HTTP failure ({error.code})."
                    ) from error
            except URLError as error:
                if attempt + 1 >= attempts:
                    raise ProviderUnavailable(
                        "Twelve Data could not be reached."
                    ) from error
            except TimeoutError as error:
                if attempt + 1 >= attempts:
                    raise ProviderUnavailable("Twelve Data request timed out.") from error
            if self.retry_delay:
                time.sleep(self.retry_delay * (2**attempt))
        raise ProviderUnavailable("Twelve Data request failed.")

    @staticmethod
    def _parse_timestamp(value: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (TypeError, ValueError) as error:
            raise MarketDataError("Twelve Data returned an invalid timestamp.") from error
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def fetch_candles(self, request: CandleRequest) -> list[Candle]:
        """Fetch, parse, and chronologically order one Forex candle series."""
        validate_request(request)
        api_request = self._build_request(request)
        payload = self._request_payload(api_request)
        values = payload.get("values")
        if not isinstance(values, list) or not values:
            raise MarketDataError("Twelve Data response contains no candle values.")
        if len(values) > request.limit:
            raise MarketDataError("Twelve Data returned more candles than requested.")

        candles = []
        for item in values:
            if not isinstance(item, dict):
                raise MarketDataError("Twelve Data returned a malformed candle.")
            try:
                candles.append(
                    Candle(
                        pair=request.pair,
                        timestamp=self._parse_timestamp(item["datetime"]),
                        open=float(item["open"]),
                        high=float(item["high"]),
                        low=float(item["low"]),
                        close=float(item["close"]),
                        volume=float(item.get("volume") or 0.0),
                    )
                )
            except (KeyError, TypeError, ValueError) as error:
                raise MarketDataError(
                    "Twelve Data returned incomplete or non-numeric OHLC data."
                ) from error

        candles.sort(key=lambda candle: candle.timestamp)
        return candles
