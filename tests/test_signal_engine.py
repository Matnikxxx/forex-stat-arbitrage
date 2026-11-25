"""Tests for paper-only mean-reversion signal generation."""

import math

import pytest

from src.pair_discovery import PairCandidate
from src.signal_engine import (
    PositionSide,
    SignalAction,
    calculate_pair_z_score,
    generate_signal,
)


def make_candidate():
    return PairCandidate(
        dependent_symbol="GBP/USD",
        independent_symbol="EUR/USD",
        correlation=0.95,
        cointegration_pvalue=0.01,
        hedge_ratio=1.0,
        intercept=0.0,
        half_life=8.0,
        observations=300,
        stability=0.9,
        score=0.08,
    )


def make_prices(last_spread=0.0, size=30):
    spread = [0.1 if index % 2 else -0.1 for index in range(size - 1)]
    spread.append(last_spread)
    return [math.exp(value) for value in spread], [1.0] * size


def signal(last_spread=0.0, **kwargs):
    dependent, independent = make_prices(last_spread)
    return generate_signal(make_candidate(), dependent, independent, **kwargs)


def test_calculate_pair_z_score_returns_finite_value():
    dependent, independent = make_prices(0.5)
    value = calculate_pair_z_score(make_candidate(), dependent, independent)
    assert math.isfinite(value)


def test_calculate_pair_z_score_rejects_short_window():
    dependent, independent = make_prices()
    with pytest.raises(ValueError, match="at least 20"):
        calculate_pair_z_score(make_candidate(), dependent, independent, 10)


def test_calculate_pair_z_score_rejects_insufficient_history():
    dependent, independent = make_prices(size=25)
    with pytest.raises(ValueError, match="Insufficient"):
        calculate_pair_z_score(make_candidate(), dependent, independent, 30)


def test_calculate_pair_z_score_rejects_mismatched_history():
    dependent, independent = make_prices()
    with pytest.raises(ValueError, match="equal lengths"):
        calculate_pair_z_score(make_candidate(), dependent, independent[:-1])


def test_positive_extreme_enters_short_spread():
    result = signal(1.0)
    assert result.action is SignalAction.ENTER_SHORT_SPREAD
    assert result.position is PositionSide.NONE


def test_negative_extreme_enters_long_spread():
    result = signal(-1.0)
    assert result.action is SignalAction.ENTER_LONG_SPREAD


def test_middle_range_holds_without_position():
    result = signal(0.0)
    assert result.action is SignalAction.HOLD


def test_long_spread_exits_near_mean():
    result = signal(0.0, current_position=PositionSide.LONG_SPREAD)
    assert result.action is SignalAction.EXIT
    assert "target" in result.reason


def test_short_spread_exits_near_mean():
    result = signal(0.0, current_position=PositionSide.SHORT_SPREAD)
    assert result.action is SignalAction.EXIT
    assert "target" in result.reason


def test_long_spread_stops_when_spread_moves_further_down():
    result = signal(-2.0, current_position=PositionSide.LONG_SPREAD)
    assert result.action is SignalAction.EXIT
    assert "stop" in result.reason


def test_short_spread_stops_when_spread_moves_further_up():
    result = signal(2.0, current_position=PositionSide.SHORT_SPREAD)
    assert result.action is SignalAction.EXIT
    assert "stop" in result.reason


def test_long_spread_holds_between_target_and_stop():
    result = signal(-0.3, current_position=PositionSide.LONG_SPREAD)
    assert result.action is SignalAction.HOLD


def test_short_spread_holds_between_target_and_stop():
    result = signal(0.3, current_position=PositionSide.SHORT_SPREAD)
    assert result.action is SignalAction.HOLD


def test_cooldown_blocks_new_entry():
    result = signal(1.0, cooldown_remaining=3)
    assert result.action is SignalAction.HOLD
    assert "cooldown" in result.reason


def test_cooldown_does_not_block_existing_position_exit():
    result = signal(0.0, current_position=PositionSide.LONG_SPREAD,
                    cooldown_remaining=3)
    assert result.action is SignalAction.EXIT


@pytest.mark.parametrize(
    "entry,exit_value,stop",
    [(2.0, 0.5, 3.0), (1.0, 0.2, 2.0)],
)
def test_valid_threshold_sets_are_accepted(entry, exit_value, stop):
    result = signal(0.0, entry_z=entry, exit_z=exit_value, stop_z=stop)
    assert result.action is SignalAction.HOLD


@pytest.mark.parametrize(
    "entry,exit_value,stop",
    [(2.0, 2.0, 3.0), (2.0, 0.5, 2.0), (0.5, 0.6, 3.0)],
)
def test_invalid_threshold_order_is_rejected(entry, exit_value, stop):
    with pytest.raises(ValueError, match="Thresholds"):
        signal(0.0, entry_z=entry, exit_z=exit_value, stop_z=stop)


def test_non_finite_threshold_is_rejected():
    with pytest.raises(ValueError, match="finite"):
        signal(0.0, entry_z=math.inf)


def test_negative_cooldown_is_rejected():
    with pytest.raises(ValueError, match="non-negative"):
        signal(0.0, cooldown_remaining=-1)


def test_signal_contains_pair_identity_and_explanation():
    result = signal(1.0)
    assert result.dependent_symbol == "GBP/USD"
    assert result.independent_symbol == "EUR/USD"
    assert result.reason
    assert result.z_score is not None
