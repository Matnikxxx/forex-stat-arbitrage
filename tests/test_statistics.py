"""Tests for the statistical calculations used by pair research."""

import math

import pytest

from src.statistics import (
    calculate_spread,
    calculate_volatility,
    estimate_half_life,
    hedge_ratio,
    log_prices,
    maximum_drawdown,
    pearson_correlation,
    percentage_returns,
    rolling_z_scores,
    validate_price_series,
    z_score,
)


def test_validate_price_series_accepts_valid_values():
    assert validate_price_series([1.1, 1.2]) == [1.1, 1.2]


@pytest.mark.parametrize("prices", [[], [1.1], [1.1, 0], [1.1, math.inf]])
def test_validate_price_series_rejects_invalid_values(prices):
    with pytest.raises(ValueError):
        validate_price_series(prices)


def test_log_prices_uses_natural_logarithm():
    assert log_prices([1.0, math.e]) == pytest.approx([0.0, 1.0])


def test_percentage_returns_calculates_consecutive_changes():
    assert percentage_returns([100, 110, 99]) == pytest.approx([0.1, -0.1])


def test_pearson_correlation_detects_perfect_positive_relationship():
    assert pearson_correlation([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0)


def test_pearson_correlation_rejects_constant_series():
    with pytest.raises(ValueError, match="constant"):
        pearson_correlation([1, 1, 1], [2, 3, 4])


def test_hedge_ratio_estimates_linear_slope():
    assert hedge_ratio([3, 5, 7], [1, 2, 3]) == pytest.approx(2.0)


def test_hedge_ratio_rejects_constant_independent_series():
    with pytest.raises(ValueError, match="constant"):
        hedge_ratio([1, 2, 3], [4, 4, 4])


def test_calculate_spread_applies_ratio_and_intercept():
    assert calculate_spread([5, 8], [2, 3], 2, 1) == pytest.approx([0, 1])


def test_calculate_spread_rejects_non_finite_ratio():
    with pytest.raises(ValueError, match="finite"):
        calculate_spread([2, 3], [1, 2], math.nan)


def test_z_score_uses_latest_observation():
    assert z_score([1, 2, 3]) == pytest.approx(math.sqrt(1.5))


def test_z_score_rejects_constant_series():
    with pytest.raises(ValueError, match="constant"):
        z_score([2, 2, 2])


def test_rolling_z_scores_aligns_results_to_input_series():
    result = rolling_z_scores([1, 2, 3, 4], 3)
    assert result[:2] == [None, None]
    assert result[2:] == pytest.approx([math.sqrt(1.5), math.sqrt(1.5)])


def test_rolling_z_scores_marks_constant_windows_as_none():
    assert rolling_z_scores([2, 2, 2], 2) == [None, None, None]


def test_rolling_z_scores_rejects_invalid_window():
    with pytest.raises(ValueError, match="at least two"):
        rolling_z_scores([1, 2, 3], 1)


def test_half_life_is_positive_for_mean_reverting_series():
    result = estimate_half_life([4, 2, 1, 0.5, 0.25])
    assert result is not None
    assert result > 0


def test_half_life_returns_none_for_non_mean_reverting_series():
    assert estimate_half_life([1, 2, 3, 4]) is None


def test_half_life_requires_three_observations():
    with pytest.raises(ValueError, match="three"):
        estimate_half_life([1, 2])


def test_calculate_volatility_uses_sample_standard_deviation():
    assert calculate_volatility([0.01, 0.02, 0.03]) == pytest.approx(0.01)


def test_calculate_volatility_requires_two_returns():
    with pytest.raises(ValueError, match="two returns"):
        calculate_volatility([0.01])


def test_maximum_drawdown_returns_peak_to_trough_fraction():
    assert maximum_drawdown([100, 120, 90, 110]) == pytest.approx(0.25)


def test_maximum_drawdown_rejects_non_positive_equity():
    with pytest.raises(ValueError, match="greater than zero"):
        maximum_drawdown([100, 0, 110])
