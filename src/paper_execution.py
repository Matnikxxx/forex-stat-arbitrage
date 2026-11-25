"""Paper-only paired execution with conservative bid/ask and slippage fills.

This module has no broker connectivity and cannot submit real orders.
"""
from dataclasses import dataclass
import math

from src.signal_engine import PositionSide


@dataclass(frozen=True)
class MarketQuote:
    bid: float
    ask: float
    timestamp: float


@dataclass(frozen=True)
class PaperPosition:
    position_id: int
    dependent_symbol: str
    independent_symbol: str
    side: PositionSide
    units_a: int
    units_b: int
    entry_a: float
    entry_b: float
    entry_fee: float


@dataclass(frozen=True)
class ClosedTrade:
    position_id: int
    dependent_symbol: str
    independent_symbol: str
    side: PositionSide
    units_a: int
    units_b: int
    entry_a: float
    entry_b: float
    exit_a: float
    exit_b: float
    gross_pnl: float
    fees: float
    net_pnl: float


@dataclass(frozen=True)
class PaperAccount:
    starting_balance: float = 1000.0
    realized_pnl: float = 0.0
    next_position_id: int = 1
    positions: tuple[PaperPosition, ...] = ()
    closed_trades: tuple[ClosedTrade, ...] = ()

    @property
    def balance(self) -> float:
        return self.starting_balance + self.realized_pnl

    @property
    def open_positions(self) -> int:
        return len(self.positions)


def _finite_positive(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite positive number.")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be a finite positive number.")
    return number


def validate_quote(quote: MarketQuote) -> MarketQuote:
    """Reject crossed, invalid, or non-positive quotes."""
    bid = _finite_positive("Bid", quote.bid)
    ask = _finite_positive("Ask", quote.ask)
    if ask < bid:
        raise ValueError("Ask cannot be below bid.")
    if isinstance(quote.timestamp, bool) or not math.isfinite(quote.timestamp):
        raise ValueError("Quote timestamp must be finite.")
    return quote


def calculate_fill_price(quote: MarketQuote, action: str, slippage: float = 0.0) -> float:
    """Fill buys at ask and sells at bid, with additional adverse slippage."""
    validate_quote(quote)
    slip = _finite_positive("Slippage", slippage) if slippage else 0.0
    if action == "BUY":
        return quote.ask + slip
    if action == "SELL":
        return quote.bid - slip
    raise ValueError("Action must be BUY or SELL.")


def calculate_pair_fees(units_a: int, units_b: int, fee_per_unit: float) -> float:
    """Calculate one-side fees for both legs."""
    if any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in (units_a, units_b)):
        raise ValueError("Both leg sizes must be positive integers.")
    if isinstance(fee_per_unit, bool) or not isinstance(fee_per_unit, (int, float)):
        raise ValueError("Fee per unit must be finite and non-negative.")
    fee = float(fee_per_unit)
    if not math.isfinite(fee) or fee < 0:
        raise ValueError("Fee per unit must be finite and non-negative.")
    return (units_a + units_b) * fee


def calculate_unrealized_pnl(position: PaperPosition, quote_a: MarketQuote, quote_b: MarketQuote) -> float:
    """Mark both legs to executable liquidation prices, less entry fees."""
    validate_quote(quote_a)
    validate_quote(quote_b)
    if position.side is PositionSide.LONG_SPREAD:
        pnl_a = (quote_a.bid - position.entry_a) * position.units_a
        pnl_b = (position.entry_b - quote_b.ask) * position.units_b
    elif position.side is PositionSide.SHORT_SPREAD:
        pnl_a = (position.entry_a - quote_a.ask) * position.units_a
        pnl_b = (quote_b.bid - position.entry_b) * position.units_b
    else:
        raise ValueError("A paper position must have a directional spread side.")
    return pnl_a + pnl_b - position.entry_fee


def calculate_account_equity(account: PaperAccount, quotes: dict[str, MarketQuote]) -> float:
    """Return balance plus unrealized PnL using current executable quotes."""
    unrealized = 0.0
    for position in account.positions:
        if position.dependent_symbol not in quotes or position.independent_symbol not in quotes:
            raise ValueError("A fresh quote is required for every open position leg.")
        unrealized += calculate_unrealized_pnl(
            position, quotes[position.dependent_symbol], quotes[position.independent_symbol]
        )
    return account.balance + unrealized


def open_paper_position(
    account: PaperAccount, *, dependent_symbol: str, independent_symbol: str,
    side: PositionSide, units_a: int, units_b: int, quote_a: MarketQuote,
    quote_b: MarketQuote, slippage: float = 0.0, fee_per_unit: float = 0.0,
    max_positions: int = 2,
) -> tuple[PaperAccount, PaperPosition]:
    """Open both simulated legs together; no real order is ever sent."""
    if not dependent_symbol or not independent_symbol or dependent_symbol == independent_symbol:
        raise ValueError("Two different pair symbols are required.")
    if side not in (PositionSide.LONG_SPREAD, PositionSide.SHORT_SPREAD):
        raise ValueError("A directional spread side is required.")
    if account.open_positions >= max_positions:
        raise ValueError("Maximum simultaneous paper positions reached.")
    if any({p.dependent_symbol, p.independent_symbol} == {dependent_symbol, independent_symbol}
           for p in account.positions):
        raise ValueError("This pair already has an open paper position.")
    action_a, action_b = (
        ("BUY", "SELL") if side is PositionSide.LONG_SPREAD else ("SELL", "BUY")
    )
    entry_a = calculate_fill_price(quote_a, action_a, slippage)
    entry_b = calculate_fill_price(quote_b, action_b, slippage)
    if entry_a <= 0 or entry_b <= 0:
        raise ValueError("Slippage resulted in a non-positive fill price.")
    fee = calculate_pair_fees(units_a, units_b, fee_per_unit)
    position = PaperPosition(
        account.next_position_id, dependent_symbol, independent_symbol, side,
        units_a, units_b, entry_a, entry_b, fee,
    )
    updated = PaperAccount(
        account.starting_balance, account.realized_pnl, account.next_position_id + 1,
        account.positions + (position,), account.closed_trades,
    )
    return updated, position


def close_paper_position(
    account: PaperAccount, position_id: int, *, quote_a: MarketQuote,
    quote_b: MarketQuote, slippage: float = 0.0, fee_per_unit: float = 0.0,
) -> tuple[PaperAccount, ClosedTrade]:
    """Close both legs and book realized net PnL in one immutable update."""
    position = next((p for p in account.positions if p.position_id == position_id), None)
    if position is None:
        raise ValueError("Open paper position was not found.")
    if position.side is PositionSide.LONG_SPREAD:
        exit_a = calculate_fill_price(quote_a, "SELL", slippage)
        exit_b = calculate_fill_price(quote_b, "BUY", slippage)
        gross = (exit_a - position.entry_a) * position.units_a + (
            position.entry_b - exit_b
        ) * position.units_b
    else:
        exit_a = calculate_fill_price(quote_a, "BUY", slippage)
        exit_b = calculate_fill_price(quote_b, "SELL", slippage)
        gross = (position.entry_a - exit_a) * position.units_a + (
            exit_b - position.entry_b
        ) * position.units_b
    exit_fees = calculate_pair_fees(position.units_a, position.units_b, fee_per_unit)
    total_fees = position.entry_fee + exit_fees
    trade = ClosedTrade(
        position.position_id, position.dependent_symbol, position.independent_symbol,
        position.side, position.units_a, position.units_b, position.entry_a,
        position.entry_b, exit_a, exit_b, gross, total_fees, gross - total_fees,
    )
    updated = PaperAccount(
        account.starting_balance, account.realized_pnl + trade.net_pnl,
        account.next_position_id,
        tuple(p for p in account.positions if p.position_id != position_id),
        account.closed_trades + (trade,),
    )
    return updated, trade
