"""Tests for forward-only, cost-aware pair backtesting."""

import math

import pytest

from src.backtesting import (
    BacktestConfig,
    BacktestTrade,
    calculate_backtest_metrics,
    calculate_round_trip_cost,
    run_pair_backtest,
    validate_backtest_inputs,
)
from src.pair_discovery import PairCandidate


def candidate():
    return PairCandidate(
        "EUR/USD", "GBP/USD", 0.9, 0.01, 1.0, 0.0,
        5.0, 200, 0.9, 0.8,
    )


def histories(length=160):
    # Smooth, bounded residual oscillation around a common log-price trend.
    first = []
    second = []
    for index in range(length):
        base = 1.1 + index * 0.0001
        first.append(base + 0.002 * math.sin(index / 5))
        second.append(base)
    return first, second


def test_backtest_input_validation_accepts_valid_data():
    y, x = histories()
    assert len(validate_backtest_inputs(y, x, BacktestConfig())[0]) == 160


@pytest.mark.parametrize("bad", [0, -1, float("nan"), float("inf")])
def test_backtest_rejects_invalid_prices(bad):
    y, x = histories()
    y[10] = bad
    with pytest.raises(ValueError):
        validate_backtest_inputs(y, x, BacktestConfig())


def test_backtest_rejects_mismatched_histories():
    y, x = histories()
    with pytest.raises(ValueError, match="match"):
        validate_backtest_inputs(y, x[:-1], BacktestConfig())


def test_backtest_rejects_short_history():
    y, x = histories(50)
    with pytest.raises(ValueError, match="signal window"):
        validate_backtest_inputs(y, x, BacktestConfig())


@pytest.mark.parametrize("kwargs", [
    {"starting_capital": 0},
    {"window": 10},
    {"units_a": 0},
    {"units_b": -1},
    {"fee_bps": -1},
    {"slippage_bps": float("nan")},
    {"entry_z": 0.4, "exit_z": 0.5},
])
def test_backtest_rejects_invalid_configuration(kwargs):
    y, x = histories()
    config = BacktestConfig(**kwargs)
    with pytest.raises(ValueError):
        validate_backtest_inputs(y, x, config)


def test_round_trip_cost_scales_with_notional():
    assert calculate_round_trip_cost(1.0, 2.0, 1000, 1000, 10) == pytest.approx(3.0)


def test_round_trip_cost_rejects_negative_basis_points():
    with pytest.raises(ValueError):
        calculate_round_trip_cost(1.0, 2.0, 1000, 1000, -1)


def test_metrics_for_no_trades_are_safe():
    result = calculate_backtest_metrics(1000, [], [1000, 1000])
    assert result.win_rate == 0
    assert result.profit_factor == 0
    assert result.expectancy == 0
    assert result.total_return == 0


def test_metrics_calculate_win_rate_profit_factor_and_expectancy():
    trades = [
        BacktestTrade("LONG_SPREAD", 1, 2, 1, 1, 1, 1, 12, 1, 1, 10, "TARGET"),
        BacktestTrade("SHORT_SPREAD", 3, 4, 1, 1, 1, 1, -6, 1, 1, -8, "STOP"),
    ]
    result = calculate_backtest_metrics(1000, trades, [1000, 1010, 1002])
    assert result.win_rate == pytest.approx(0.5)
    assert result.profit_factor == pytest.approx(1.25)
    assert result.expectancy == pytest.approx(1.0)


def test_backtest_is_deterministic():
    y, x = histories()
    config = BacktestConfig(window=30, entry_z=1.0, exit_z=0.3, stop_z=2.5)
    first = run_pair_backtest(candidate(), y, x, config)
    second = run_pair_backtest(candidate(), y, x, config)
    assert first == second


def test_backtest_never_enters_before_signal_is_available():
    y, x = histories()
    config = BacktestConfig(window=30, entry_z=0.8, exit_z=0.2, stop_z=2.5)
    result = run_pair_backtest(candidate(), y, x, config)
    assert all(trade.entry_index >= config.window for trade in result.trades)


def test_backtest_charges_entry_and_exit_costs():
    y, x = histories()
    config = BacktestConfig(
        window=30, entry_z=0.8, exit_z=0.2, stop_z=2.5,
        fee_bps=1, slippage_bps=2,
    )
    result = run_pair_backtest(candidate(), y, x, config)
    for trade in result.trades:
        assert trade.fees > 0
        assert trade.slippage_cost > 0
        assert trade.net_pnl == pytest.approx(
            trade.gross_pnl - trade.fees - trade.slippage_cost
        )


def test_backtest_result_equity_matches_final_return():
    y, x = histories()
    result = run_pair_backtest(
        candidate(), y, x, BacktestConfig(window=30, entry_z=0.8, exit_z=0.2)
    )
    assert result.ending_equity == pytest.approx(result.equity_curve[-1])
    assert result.total_return == pytest.approx(
        result.ending_equity / result.starting_capital - 1
    )


def test_open_trade_is_closed_at_end_of_history():
    y, x = histories()
    config = BacktestConfig(window=30, entry_z=0.8, exit_z=0.2, stop_z=10)
    result = run_pair_backtest(candidate(), y, x, config)
    if result.trades:
        assert result.trades[-1].exit_reason in {"END_OF_DATA", "STOP", "MEAN_REVERSION"}
