"""Statistical helpers for researching mean-reversion currency pairs."""

import math
from collections.abc import Sequence


def validate_price_series(prices: Sequence[float]) -> list[float]:
    """Return finite positive prices, requiring at least two observations."""
    values = [float(price) for price in prices]
    if len(values) < 2:
        raise ValueError("At least two prices are required.")
    if not all(math.isfinite(value) and value > 0 for value in values):
        raise ValueError("Prices must be finite and greater than zero.")
    return values


def log_prices(prices: Sequence[float]) -> list[float]:
    """Convert positive prices to natural logarithms."""
    return [math.log(price) for price in validate_price_series(prices)]


def percentage_returns(prices: Sequence[float]) -> list[float]:
    """Calculate simple percentage returns between consecutive prices."""
    values = validate_price_series(prices)
    return [
        (current / previous) - 1.0
        for previous, current in zip(values, values[1:])
    ]


def pearson_correlation(first: Sequence[float], second: Sequence[float]) -> float:
    """Calculate Pearson correlation for two equally sized numeric series."""
    x, y = _paired_series(first, second)
    mean_x = sum(x) / len(x)
    mean_y = sum(y) / len(y)
    centered_x = [value - mean_x for value in x]
    centered_y = [value - mean_y for value in y]
    sum_x = sum(value * value for value in centered_x)
    sum_y = sum(value * value for value in centered_y)
    if sum_x == 0 or sum_y == 0:
        raise ValueError("Correlation is undefined for a constant series.")
    covariance = sum(
        left * right for left, right in zip(centered_x, centered_y)
    )
    return covariance / math.sqrt(sum_x * sum_y)


def hedge_ratio(dependent: Sequence[float], independent: Sequence[float]) -> float:
    """Estimate the OLS slope for dependent prices against independent prices."""
    y, x = _paired_series(dependent, independent)
    mean_x = sum(x) / len(x)
    mean_y = sum(y) / len(y)
    variance_x = sum((value - mean_x) ** 2 for value in x)
    if variance_x == 0:
        raise ValueError("Hedge ratio is undefined for a constant series.")
    covariance = sum(
        (left - mean_y) * (right - mean_x) for left, right in zip(y, x)
    )
    return covariance / variance_x


def calculate_spread(
    dependent: Sequence[float],
    independent: Sequence[float],
    ratio: float,
    intercept: float = 0.0,
) -> list[float]:
    """Calculate the residual spread: dependent - intercept - ratio * independent."""
    y, x = _paired_series(dependent, independent)
    if not math.isfinite(ratio) or not math.isfinite(intercept):
        raise ValueError("Hedge ratio and intercept must be finite.")
    return [
        left - intercept - ratio * right for left, right in zip(y, x)
    ]


def z_score(values: Sequence[float]) -> float:
    """Calculate the population-standard-deviation z-score of the latest value."""
    series = _finite_series(values)
    mean = sum(series) / len(series)
    variance = sum((value - mean) ** 2 for value in series) / len(series)
    deviation = math.sqrt(variance)
    if deviation == 0:
        raise ValueError("Z-score is undefined for a constant series.")
    return (series[-1] - mean) / deviation


def rolling_z_scores(
    values: Sequence[float], window: int
) -> list[float | None]:
    """Calculate trailing z-scores; leading values without a full window are None."""
    series = _finite_series(values)
    if window < 2:
        raise ValueError("Rolling window must be at least two.")
    if window > len(series):
        raise ValueError("Rolling window cannot exceed the series length.")
    results: list[float | None] = [None] * (window - 1)
    for end in range(window, len(series) + 1):
        sample = series[end - window : end]
        mean = sum(sample) / window
        variance = sum((value - mean) ** 2 for value in sample) / window
        deviation = math.sqrt(variance)
        results.append(
            None if deviation == 0 else (sample[-1] - mean) / deviation
        )
    return results


def estimate_half_life(spread: Sequence[float]) -> float | None:
    """Estimate mean-reversion half-life in observations using an AR(1) slope."""
    values = _finite_series(spread)
    if len(values) < 3:
        raise ValueError("At least three spread observations are required.")
    lagged = values[:-1]
    changes = [right - left for left, right in zip(values, values[1:])]
    mean_lagged = sum(lagged) / len(lagged)
    mean_changes = sum(changes) / len(changes)
    variance = sum((value - mean_lagged) ** 2 for value in lagged)
    if variance == 0:
        raise ValueError("Half-life is undefined for a constant spread.")
    slope = sum(
        (left - mean_lagged) * (change - mean_changes)
        for left, change in zip(lagged, changes)
    ) / variance
    if slope >= 0:
        return None
    return -math.log(2) / slope


def calculate_volatility(returns: Sequence[float]) -> float:
    """Calculate sample standard deviation of a return series."""
    values = _finite_series(returns)
    if len(values) < 2:
        raise ValueError("At least two returns are required.")
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def maximum_drawdown(equity_curve: Sequence[float]) -> float:
    """Return the largest peak-to-trough percentage decline as a fraction."""
    values = _finite_series(equity_curve)
    if any(value <= 0 for value in values):
        raise ValueError("Equity values must be greater than zero.")
    peak = values[0]
    worst_drawdown = 0.0
    for value in values:
        peak = max(peak, value)
        drawdown = (peak - value) / peak
        worst_drawdown = max(worst_drawdown, drawdown)
    return worst_drawdown


def _finite_series(values: Sequence[float]) -> list[float]:
    """Convert a numeric series to floats and reject empty or non-finite data."""
    series = [float(value) for value in values]
    if not series:
        raise ValueError("A non-empty series is required.")
    if not all(math.isfinite(value) for value in series):
        raise ValueError("Series values must be finite.")
    return series


def _paired_series(
    first: Sequence[float], second: Sequence[float]
) -> tuple[list[float], list[float]]:
    """Validate and return two finite series with matching lengths."""
    left = _finite_series(first)
    right = _finite_series(second)
    if len(left) != len(right):
        raise ValueError("Paired series must have equal lengths.")
    if len(left) < 2:
        raise ValueError("At least two paired observations are required.")
    return left, right
