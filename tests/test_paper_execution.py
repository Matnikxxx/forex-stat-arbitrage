"""Tests for paper-only paired execution and cost-aware accounting."""
import pytest

from src.paper_execution import (
    MarketQuote, PaperAccount, calculate_account_equity, calculate_fill_price,
    calculate_pair_fees, calculate_unrealized_pnl, close_paper_position,
    open_paper_position, validate_quote,
)
from src.signal_engine import PositionSide


def qa(bid=1.1000, ask=1.1002, timestamp=1000.0):
    return MarketQuote(bid, ask, timestamp)


def open_long(**kwargs):
    return open_paper_position(
        PaperAccount(), dependent_symbol="EUR/USD", independent_symbol="GBP/USD",
        side=PositionSide.LONG_SPREAD, units_a=1000, units_b=1000,
        quote_a=qa(), quote_b=qa(1.2500, 1.2502), **kwargs,
    )


def test_quote_rejects_crossed_market():
    with pytest.raises(ValueError, match="Ask"):
        validate_quote(qa(1.2, 1.1))


def test_quote_rejects_non_positive_price():
    with pytest.raises(ValueError):
        validate_quote(qa(0, 1))


def test_buy_uses_ask_and_slippage():
    assert calculate_fill_price(qa(), "BUY", 0.0001) == pytest.approx(1.1003)


def test_sell_uses_bid_and_slippage():
    assert calculate_fill_price(qa(), "SELL", 0.0001) == pytest.approx(1.0999)


def test_fill_rejects_unknown_action():
    with pytest.raises(ValueError):
        calculate_fill_price(qa(), "HOLD")


def test_fee_calculation_for_both_legs():
    assert calculate_pair_fees(1000, 2000, 0.00001) == pytest.approx(0.03)


def test_fee_rejects_negative_value():
    with pytest.raises(ValueError):
        calculate_pair_fees(1000, 1000, -1)


def test_open_creates_two_leg_position():
    account, position = open_long()
    assert len(account.positions) == 1
    assert position.entry_a == pytest.approx(1.1002)
    assert position.entry_b == pytest.approx(1.25)


def test_open_applies_fees():
    account, position = open_long(fee_per_unit=0.00001)
    assert position.entry_fee == pytest.approx(0.02)


def test_open_rejects_duplicate_pair_in_reverse_order():
    account, _ = open_long()
    with pytest.raises(ValueError, match="already"):
        open_paper_position(
            account, dependent_symbol="GBP/USD", independent_symbol="EUR/USD",
            side=PositionSide.SHORT_SPREAD, units_a=1000, units_b=1000,
            quote_a=qa(), quote_b=qa(),
        )


def test_open_enforces_maximum_positions():
    account, _ = open_long()
    account, _ = open_paper_position(
        account, dependent_symbol="AUD/USD", independent_symbol="USD/JPY",
        side=PositionSide.LONG_SPREAD, units_a=1000, units_b=1000,
        quote_a=qa(), quote_b=qa(),
    )
    with pytest.raises(ValueError, match="Maximum"):
        open_paper_position(
            account, dependent_symbol="EUR/JPY", independent_symbol="GBP/JPY",
            side=PositionSide.LONG_SPREAD, units_a=1000, units_b=1000,
            quote_a=qa(), quote_b=qa(),
        )


def test_unrealized_pnl_uses_liquidation_side_of_spread():
    _, position = open_long()
    pnl = calculate_unrealized_pnl(
        position, qa(1.1010, 1.1012), qa(1.2490, 1.2492)
    )
    assert pnl == pytest.approx(1.6)


def test_account_equity_includes_unrealized_pnl():
    account, _ = open_long()
    equity = calculate_account_equity(
        account, {"EUR/USD": qa(1.1010, 1.1012), "GBP/USD": qa(1.2490, 1.2492)}
    )
    assert equity == pytest.approx(1001.6)


def test_account_equity_requires_all_open_quotes():
    account, _ = open_long()
    with pytest.raises(ValueError, match="fresh quote"):
        calculate_account_equity(account, {"EUR/USD": qa()})


def test_close_books_realized_pnl_and_removes_position():
    account, position = open_long()
    updated, trade = close_paper_position(
        account, position.position_id, quote_a=qa(1.1010, 1.1012),
        quote_b=qa(1.2490, 1.2492),
    )
    assert updated.positions == ()
    assert updated.realized_pnl == pytest.approx(1.6)
    assert trade.net_pnl == pytest.approx(1.6)
    assert len(updated.closed_trades) == 1


def test_close_charges_entry_and_exit_fees():
    account, position = open_long(fee_per_unit=0.00001)
    updated, trade = close_paper_position(
        account, position.position_id, quote_a=qa(1.1010, 1.1012),
        quote_b=qa(1.2490, 1.2492), fee_per_unit=0.00001,
    )
    assert trade.fees == pytest.approx(0.04)
    assert updated.realized_pnl == pytest.approx(1.56)


def test_close_rejects_unknown_position():
    with pytest.raises(ValueError, match="not found"):
        close_paper_position(PaperAccount(), 42, quote_a=qa(), quote_b=qa())


def test_short_spread_pnl_direction():
    account, position = open_paper_position(
        PaperAccount(), dependent_symbol="EUR/USD", independent_symbol="GBP/USD",
        side=PositionSide.SHORT_SPREAD, units_a=1000, units_b=1000,
        quote_a=qa(), quote_b=qa(1.2500, 1.2502),
    )
    updated, trade = close_paper_position(
        account, position.position_id, quote_a=qa(1.0990, 1.0992),
        quote_b=qa(1.2510, 1.2512),
    )
    assert trade.net_pnl == pytest.approx(1.6)
    assert updated.balance == pytest.approx(1001.6)


def test_slippage_cannot_create_negative_fill():
    with pytest.raises(ValueError, match="non-positive"):
        open_paper_position(
            PaperAccount(), dependent_symbol="EUR/USD", independent_symbol="GBP/USD",
            side=PositionSide.LONG_SPREAD, units_a=1000, units_b=1000,
            quote_a=qa(), quote_b=qa(0.0001, 0.0002),
            slippage=0.001,
        )


def test_open_rejects_non_directional_signal():
    with pytest.raises(ValueError, match="directional"):
        open_paper_position(
            PaperAccount(), dependent_symbol="EUR/USD", independent_symbol="GBP/USD",
            side=PositionSide.NONE, units_a=1000, units_b=1000,
            quote_a=qa(), quote_b=qa(),
        )
