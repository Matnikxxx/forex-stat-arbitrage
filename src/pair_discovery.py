"""Cointegration research and automatic currency-pair discovery."""

from dataclasses import dataclass
import math
from collections.abc import Sequence

from statsmodels.tsa.stattools import coint

from src.statistics import (
    calculate_spread,
    estimate_half_life,
    hedge_ratio,
    log_prices,
    pearson_correlation,
)


@dataclass(frozen=True)
class PairCandidate:
    """Research result for one ordered pair of price series."""

    dependent_symbol: str
    independent_symbol: str
    correlation: float
    cointegration_pvalue: float
    hedge_ratio: float
    intercept: float
    half_life: float
    observations: int
    stability: float
    score: float


def _validate_pair(
    dependent: Sequence[float], independent: Sequence[float], min_observations: int
) -> tuple[list[float], list[float]]:
    """Validate aligned positive price histories for pair research."""
    if min_observations < 20:
        raise ValueError("Minimum observations must be at least 20.")
    y = [float(value) for value in dependent]
    x = [float(value) for value in independent]
    if len(y) != len(x):
        raise ValueError("Pair histories must have equal lengths.")
    if len(y) < min_observations:
        raise ValueError("Insufficient observations for pair research.")
    if any(not math.isfinite(v) or v <= 0 for v in y + x):
        raise ValueError("Prices must be finite and greater than zero.")
    return y, x


def engle_granger_test(
    dependent: Sequence[float],
    independent: Sequence[float],
    min_observations: int = 100,
) -> tuple[float, float]:
    """Return Engle-Granger test statistic and p-value for log price levels."""
    y, x = _validate_pair(dependent, independent, min_observations)
    statistic, pvalue, _ = coint(log_prices(y), log_prices(x), trend="c")
    if not math.isfinite(statistic) or not math.isfinite(pvalue):
        raise ValueError("Cointegration test produced a non-finite result.")
    return float(statistic), float(pvalue)


def rolling_hedge_ratios(
    dependent: Sequence[float], independent: Sequence[float], window: int
) -> list[float]:
    """Calculate rolling OLS hedge ratios on log prices."""
    if window < 20:
        raise ValueError("Rolling window must be at least 20 observations.")
    y, x = _validate_pair(dependent, independent, window)
    log_y = log_prices(y)
    log_x = log_prices(x)
    return [
        hedge_ratio(log_y[end - window : end], log_x[end - window : end])
        for end in range(window, len(y) + 1)
    ]


def hedge_ratio_stability(ratios: Sequence[float]) -> float:
    """Return a bounded stability score; 1 is stable and 0 is unstable."""
    values = [float(value) for value in ratios]
    if len(values) < 2:
        raise ValueError("At least two hedge ratios are required.")
    if any(not math.isfinite(value) for value in values):
        raise ValueError("Hedge ratios must be finite.")
    mean = sum(values) / len(values)
    scale = max(abs(mean), 1e-12)
    variation = math.sqrt(sum((v - mean) ** 2 for v in values) / len(values)) / scale
    return 1.0 / (1.0 + variation)


def evaluate_pair(
    dependent_symbol: str,
    independent_symbol: str,
    dependent: Sequence[float],
    independent: Sequence[float],
    *,
    min_observations: int = 100,
    max_pvalue: float = 0.05,
    min_correlation: float = 0.5,
    stability_window: int = 100,
) -> PairCandidate | None:
    """Evaluate a pair; return None when research filters reject it."""
    if not dependent_symbol or not independent_symbol:
        raise ValueError("Both pair symbols are required.")
    if dependent_symbol == independent_symbol:
        raise ValueError("A currency pair must contain two different symbols.")
    if not 0 < max_pvalue < 1:
        raise ValueError("Maximum p-value must be between zero and one.")
    if not 0 <= min_correlation <= 1:
        raise ValueError("Minimum correlation must be between zero and one.")
    y, x = _validate_pair(dependent, independent, min_observations)
    log_y = log_prices(y)
    log_x = log_prices(x)
    correlation = pearson_correlation(log_y, log_x)
    if abs(correlation) < min_correlation:
        return None

    statistic, pvalue = engle_granger_test(y, x, min_observations)
    if pvalue > max_pvalue:
        return None

    ratio = hedge_ratio(log_y, log_x)
    mean_x = sum(log_x) / len(log_x)
    mean_y = sum(log_y) / len(log_y)
    intercept = mean_y - ratio * mean_x
    spread = calculate_spread(log_y, log_x, ratio, intercept)
    half_life = estimate_half_life(spread)
    if half_life is None or not math.isfinite(half_life) or half_life <= 0:
        return None

    window = min(stability_window, len(y))
    if window < 20:
        return None
    ratios = rolling_hedge_ratios(y, x, window)
    stability = hedge_ratio_stability(ratios)
    if stability < 0.5:
        return None

    score = (1.0 - pvalue) * abs(correlation) * stability / (1.0 + half_life)
    return PairCandidate(
        dependent_symbol=dependent_symbol,
        independent_symbol=independent_symbol,
        correlation=correlation,
        cointegration_pvalue=pvalue,
        hedge_ratio=ratio,
        intercept=intercept,
        half_life=half_life,
        observations=len(y),
        stability=stability,
        score=score,
    )


def discover_pairs(
    price_data: dict[str, Sequence[float]],
    *,
    min_observations: int = 100,
    max_pvalue: float = 0.05,
    min_correlation: float = 0.5,
) -> list[PairCandidate]:
    """Screen all unique symbol combinations and rank accepted candidates."""
    symbols = sorted(price_data)
    candidates: list[PairCandidate] = []
    for index, first in enumerate(symbols):
        for second in symbols[index + 1 :]:
            try:
                candidate = evaluate_pair(
                    first,
                    second,
                    price_data[first],
                    price_data[second],
                    min_observations=min_observations,
                    max_pvalue=max_pvalue,
                    min_correlation=min_correlation,
                )
            except ValueError:
                continue
            if candidate is not None:
                candidates.append(candidate)
    return sorted(candidates, key=lambda item: item.score, reverse=True)
