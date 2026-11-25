"""Tests for broker-independent paper-trading risk controls."""

import math

import pytest

from src.risk_management import (
    PortfolioRisk,
    aggregate_currency_exposure,
    assess_new_position,
    calculate_daily_loss_fraction,
    calculate_drawdown,
    calculate_position_size,
    calculate_risk_budget,
    has_duplicate_pair,
)


def portfolio(**overrides):
    values = {
        "equity": 1000.0,
        "peak_equity": 1000.0,
        "daily_pnl": 0.0,
        "open_risk": 0.0,
        "open_positions": 0,
    }
    values.update(overrides)
    return PortfolioRisk(**values)


def sizing(**overrides):
    values = {
        "equity": 1000.0,
        "stop_pips_a": 20.0,
        "stop_pips_b": 20.0,
        "pip_value_per_unit_a": 0.0001,
        "pip_value_per_unit_b": 0.0001,
        "hedge_ratio": 1.0,
        "unit_step": 1000,
    }
    values.update(overrides)
    return calculate_position_size(**values)


def test_default_risk_budget_is_one_percent():
    assert calculate_risk_budget(1000) == pytest.approx(10)


@pytest.mark.parametrize("equity", [0, -1, math.inf, math.nan, True])
def test_risk_budget_rejects_invalid_equity(equity):
    with pytest.raises(ValueError):
        calculate_risk_budget(equity)


@pytest.mark.parametrize("fraction", [0, -0.1, 0.0101, math.inf, True])
def test_risk_budget_rejects_invalid_risk_fraction(fraction):
    with pytest.raises(ValueError):
        calculate_risk_budget(1000, fraction)


def test_position_size_stays_within_one_percent_budget():
    result = sizing()
    assert result.risk_amount <= 10
    assert result.risk_fraction <= 0.01
    assert result.base_units > 0
    assert result.hedge_units > 0


def test_position_size_scales_hedge_leg_by_hedge_ratio():
    result = sizing(hedge_ratio=1.5)
    assert result.hedge_units == int(result.base_units * 1.5 // 1000) * 1000


@pytest.mark.parametrize(
    "changes",
    [
        {"stop_pips_a": 0},
        {"stop_pips_b": -1},
        {"pip_value_per_unit_a": math.nan},
        {"pip_value_per_unit_b": math.inf},
        {"hedge_ratio": 0},
        {"hedge_ratio": math.nan},
        {"unit_step": 0},
        {"unit_step": True},
    ],
)
def test_position_size_rejects_invalid_inputs(changes):
    with pytest.raises(ValueError):
        sizing(**changes)


def test_position_size_rejects_budget_too_small_for_minimum_step():
    with pytest.raises(ValueError, match="too small"):
        sizing(equity=1)


def test_drawdown_is_measured_from_peak():
    assert calculate_drawdown(900, 1000) == pytest.approx(0.10)


def test_drawdown_rejects_equity_above_peak():
    with pytest.raises(ValueError, match="cannot exceed"):
        calculate_drawdown(1100, 1000)


def test_daily_loss_fraction_ignores_daily_profit():
    assert calculate_daily_loss_fraction(1000, 25) == 0
    assert calculate_daily_loss_fraction(1000, -30) == pytest.approx(0.03)


def test_allows_position_when_portfolio_is_within_limits():
    decision = assess_new_position(portfolio(), 10)
    assert decision.allowed
    assert decision.available_risk == pytest.approx(20)


def test_blocks_third_simultaneous_position():
    decision = assess_new_position(portfolio(open_positions=2), 5)
    assert not decision.allowed
    assert "Maximum simultaneous" in decision.reason


def test_blocks_entry_at_three_percent_daily_loss():
    decision = assess_new_position(portfolio(daily_pnl=-30), 5)
    assert not decision.allowed
    assert "Daily loss" in decision.reason


def test_blocks_entry_at_ten_percent_drawdown():
    decision = assess_new_position(
        portfolio(equity=900, peak_equity=1000), 5
    )
    assert not decision.allowed
    assert "drawdown" in decision.reason


def test_blocks_entry_that_exceeds_combined_open_risk():
    decision = assess_new_position(portfolio(open_risk=15), 6)
    assert not decision.allowed
    assert "open-risk" in decision.reason
    assert decision.available_risk == pytest.approx(5)


def test_allows_entry_at_exact_remaining_open_risk_budget():
    decision = assess_new_position(portfolio(open_risk=10), 10)
    assert decision.allowed


def test_currency_exposure_aggregates_signed_values():
    result = aggregate_currency_exposure(
        [
            {"currency": "usd", "amount": 100},
            {"currency": "USD", "amount": -40},
            {"currency": "EUR", "amount": 25},
        ]
    )
    assert result == {"USD": 60, "EUR": 25}


@pytest.mark.parametrize(
    "positions",
    [
        [{"currency": "", "amount": 1}],
        [{"currency": "USD", "amount": math.inf}],
        [{"currency": "USD", "amount": True}],
        [{"currency": "USD", "amount": "10"}],
    ],
)
def test_currency_exposure_rejects_invalid_records(positions):
    with pytest.raises(ValueError):
        aggregate_currency_exposure(positions)


def test_duplicate_pair_detection_ignores_leg_order_and_case():
    assert has_duplicate_pair([("EUR/USD", "GBP/USD")], ("gbp/usd", "eur/usd"))


def test_duplicate_pair_detection_allows_new_pair():
    assert not has_duplicate_pair([("EUR/USD", "GBP/USD")], ("AUD/USD", "USD/JPY"))


def test_duplicate_pair_rejects_same_symbol_twice():
    with pytest.raises(ValueError, match="two different"):
        has_duplicate_pair([], ("EUR/USD", "eur/usd"))
