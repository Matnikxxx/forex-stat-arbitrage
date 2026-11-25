"""Tests for cointegration and currency-pair discovery."""

import math

import numpy as np
import pytest

from src.pair_discovery import (
    discover_pairs,
    engle_granger_test,
    evaluate_pair,
    hedge_ratio_stability,
    rolling_hedge_ratios,
)


def make_cointegrated(seed=7, size=300):
    rng = np.random.default_rng(seed)
    common = np.cumsum(rng.normal(0, 0.01, size))
    residual = np.zeros(size)
    noise = rng.normal(0, 0.008, size)
    for index in range(1, size):
        residual[index] = 0.65 * residual[index - 1] + noise[index]
    first = np.exp(1.1 + common)
    second = np.exp(0.4 + 1.4 * common + residual)
    return second.tolist(), first.tolist()


def make_random_walks(seed=19, size=300):
    rng = np.random.default_rng(seed)
    first = np.exp(np.cumsum(rng.normal(0, 0.01, size)) + 4)
    second = np.exp(np.cumsum(rng.normal(0, 0.01, size)) + 4)
    return first.tolist(), second.tolist()


def test_engle_granger_detects_cointegrated_series():
    dependent, independent = make_cointegrated()
    _, pvalue = engle_granger_test(dependent, independent)
    assert pvalue < 0.05


def test_engle_granger_does_not_usually_accept_independent_walks():
    first, second = make_random_walks()
    _, pvalue = engle_granger_test(first, second)
    assert pvalue > 0.01


def test_engle_granger_rejects_insufficient_history():
    with pytest.raises(ValueError, match="Insufficient"):
        engle_granger_test([1.0] * 30, [1.0] * 30)


def test_engle_granger_rejects_mismatched_lengths():
    with pytest.raises(ValueError, match="equal lengths"):
        engle_granger_test([1.0] * 100, [1.0] * 99)


def test_engle_granger_rejects_non_positive_prices():
    first, second = make_cointegrated()
    first[10] = 0
    with pytest.raises(ValueError, match="greater than zero"):
        engle_granger_test(first, second)


def test_rolling_hedge_ratios_returns_expected_number_of_windows():
    first, second = make_cointegrated(size=120)
    ratios = rolling_hedge_ratios(first, second, 40)
    assert len(ratios) == 81
    assert all(math.isfinite(value) for value in ratios)


def test_rolling_hedge_ratios_rejects_small_window():
    first, second = make_cointegrated()
    with pytest.raises(ValueError, match="at least 20"):
        rolling_hedge_ratios(first, second, 10)


def test_rolling_hedge_ratios_rejects_short_data():
    with pytest.raises(ValueError, match="Insufficient"):
        rolling_hedge_ratios([1.0] * 25, [1.0] * 25, 30)


def test_hedge_ratio_stability_is_one_for_constant_ratios():
    assert hedge_ratio_stability([1.5, 1.5, 1.5]) == pytest.approx(1.0)


def test_hedge_ratio_stability_decreases_with_variation():
    assert hedge_ratio_stability([1, 1.1, 0.9, 1]) < 1.0


def test_hedge_ratio_stability_rejects_single_value():
    with pytest.raises(ValueError, match="two"):
        hedge_ratio_stability([1.0])


def test_hedge_ratio_stability_rejects_non_finite_values():
    with pytest.raises(ValueError, match="finite"):
        hedge_ratio_stability([1.0, math.inf])


def test_evaluate_pair_accepts_cointegrated_candidate():
    dependent, independent = make_cointegrated()
    result = evaluate_pair("GBP/USD", "EUR/USD", dependent, independent)
    assert result is not None
    assert result.cointegration_pvalue < 0.05
    assert result.observations == 300
    assert result.score > 0


def test_evaluate_pair_rejects_same_symbol():
    dependent, independent = make_cointegrated()
    with pytest.raises(ValueError, match="different"):
        evaluate_pair("EUR/USD", "EUR/USD", dependent, independent)


def test_evaluate_pair_rejects_invalid_thresholds():
    dependent, independent = make_cointegrated()
    with pytest.raises(ValueError, match="p-value"):
        evaluate_pair(
            "GBP/USD", "EUR/USD", dependent, independent, max_pvalue=1.0
        )


def test_evaluate_pair_rejects_uncorrelated_pair():
    first, second = make_random_walks()
    result = evaluate_pair("AUD/USD", "USD/JPY", first, second)
    assert result is None


def test_discover_pairs_returns_ranked_cointegrated_candidates():
    dependent, independent = make_cointegrated()
    results = discover_pairs(
        {"GBP/USD": dependent, "EUR/USD": independent}
    )
    assert len(results) == 1
    assert results[0].score > 0


def test_discover_pairs_skips_invalid_histories_and_continues():
    dependent, independent = make_cointegrated()
    results = discover_pairs(
        {
            "EUR/USD": independent,
            "GBP/USD": dependent,
            "AUD/USD": [1.0] * 10,
        }
    )
    assert len(results) <= 1
