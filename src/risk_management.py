"""Broker-independent risk controls for paper pair trading."""

from dataclasses import dataclass
import math
from collections.abc import Sequence


@dataclass(frozen=True)
class PositionSizing:
    """Calculated size for both legs of one simulated pair trade."""

    base_units: int
    hedge_units: int
    risk_amount: float
    risk_fraction: float
    leg_a_risk: float
    leg_b_risk: float


@dataclass(frozen=True)
class RiskDecision:
    """Whether a new simulated position is permitted."""

    allowed: bool
    reason: str
    available_risk: float


@dataclass(frozen=True)
class PortfolioRisk:
    """Current portfolio risk inputs, expressed in account currency."""

    equity: float
    peak_equity: float
    daily_pnl: float
    open_risk: float
    open_positions: int


def _positive_finite(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite positive number.")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be a finite positive number.")
    return number


def calculate_risk_budget(
    equity: float, risk_fraction: float = 0.01
) -> float:
    """Return the maximum account-currency risk for one paired trade."""
    equity_value = _positive_finite("Equity", equity)
    if (
        isinstance(risk_fraction, bool)
        or not isinstance(risk_fraction, (int, float))
        or not math.isfinite(risk_fraction)
        or not 0 < risk_fraction <= 0.01
    ):
        raise ValueError("Risk fraction must be greater than 0 and at most 1%.")
    return equity_value * float(risk_fraction)


def calculate_position_size(
    *,
    equity: float,
    stop_pips_a: float,
    stop_pips_b: float,
    pip_value_per_unit_a: float,
    pip_value_per_unit_b: float,
    hedge_ratio: float,
    unit_step: int = 1000,
    risk_fraction: float = 0.01,
) -> PositionSizing:
    """Size a paired position so estimated stop risk stays within budget.

    Pip values are account-currency values for one unit of each leg.
    The hedge leg is scaled by the absolute hedge ratio.
    """
    budget = calculate_risk_budget(equity, risk_fraction)
    stop_a = _positive_finite("Leg A stop pips", stop_pips_a)
    stop_b = _positive_finite("Leg B stop pips", stop_pips_b)
    pip_a = _positive_finite("Leg A pip value", pip_value_per_unit_a)
    pip_b = _positive_finite("Leg B pip value", pip_value_per_unit_b)
    if isinstance(hedge_ratio, bool) or not isinstance(hedge_ratio, (int, float)):
        raise ValueError("Hedge ratio must be finite and non-zero.")
    ratio = float(hedge_ratio)
    if not math.isfinite(ratio) or ratio == 0:
        raise ValueError("Hedge ratio must be finite and non-zero.")
    if isinstance(unit_step, bool) or not isinstance(unit_step, int) or unit_step < 1:
        raise ValueError("Unit step must be a positive integer.")

    risk_per_base_unit = stop_a * pip_a + abs(ratio) * stop_b * pip_b
    raw_units = budget / risk_per_base_unit
    base_units = int(raw_units // unit_step) * unit_step
    if base_units < unit_step:
        raise ValueError("Risk budget is too small for the minimum unit step.")

    hedge_units = int((base_units * abs(ratio)) // unit_step) * unit_step
    if hedge_units < unit_step:
        raise ValueError("Hedge ratio produces less than the minimum hedge size.")

    leg_a_risk = base_units * stop_a * pip_a
    leg_b_risk = hedge_units * stop_b * pip_b
    total_risk = leg_a_risk + leg_b_risk
    # Rounding the hedge leg down cannot exceed the budget; retain a
    # final guard against floating-point edge cases.
    if total_risk > budget + 1e-9:
        raise ValueError("Calculated paired risk exceeds the risk budget.")

    return PositionSizing(
        base_units=base_units,
        hedge_units=hedge_units,
        risk_amount=total_risk,
        risk_fraction=total_risk / float(equity),
        leg_a_risk=leg_a_risk,
        leg_b_risk=leg_b_risk,
    )


def calculate_drawdown(equity: float, peak_equity: float) -> float:
    """Return percentage drawdown from the account's equity peak."""
    current = _positive_finite("Equity", equity)
    peak = _positive_finite("Peak equity", peak_equity)
    if current > peak:
        raise ValueError("Equity cannot exceed peak equity.")
    return (peak - current) / peak


def calculate_daily_loss_fraction(equity: float, daily_pnl: float) -> float:
    """Return daily loss as a fraction of current equity; gains return zero."""
    current = _positive_finite("Equity", equity)
    if isinstance(daily_pnl, bool) or not isinstance(daily_pnl, (int, float)):
        raise ValueError("Daily PnL must be finite.")
    pnl = float(daily_pnl)
    if not math.isfinite(pnl):
        raise ValueError("Daily PnL must be finite.")
    return max(0.0, -pnl / current)


def assess_new_position(
    portfolio: PortfolioRisk,
    proposed_risk: float,
    *,
    max_positions: int = 2,
    max_daily_loss_fraction: float = 0.03,
    max_drawdown_fraction: float = 0.10,
    max_total_open_risk_fraction: float = 0.02,
) -> RiskDecision:
    """Apply portfolio-level limits before accepting a paper entry."""
    equity = _positive_finite("Equity", portfolio.equity)
    peak = _positive_finite("Peak equity", portfolio.peak_equity)
    if peak < equity:
        raise ValueError("Peak equity cannot be below current equity.")
    if isinstance(portfolio.daily_pnl, bool) or not math.isfinite(portfolio.daily_pnl):
        raise ValueError("Daily PnL must be finite.")
    if isinstance(portfolio.open_risk, bool) or not math.isfinite(portfolio.open_risk):
        raise ValueError("Open risk must be finite.")
    if portfolio.open_risk < 0 or portfolio.open_positions < 0:
        raise ValueError("Open risk and position count cannot be negative.")
    proposed = _positive_finite("Proposed risk", proposed_risk)
    if isinstance(max_positions, bool) or not isinstance(max_positions, int) or max_positions < 1:
        raise ValueError("Maximum positions must be a positive integer.")
    limits = (max_daily_loss_fraction, max_drawdown_fraction, max_total_open_risk_fraction)
    if any(
        isinstance(limit, bool)
        or not isinstance(limit, (int, float))
        or not math.isfinite(limit)
        or not 0 < limit <= 1
        for limit in limits
    ):
        raise ValueError("Portfolio risk limits must be finite fractions in (0, 1].")

    available = max(0.0, equity * max_total_open_risk_fraction - portfolio.open_risk)
    if portfolio.open_positions >= max_positions:
        return RiskDecision(False, "Maximum simultaneous positions reached.", available)
    if calculate_daily_loss_fraction(equity, portfolio.daily_pnl) >= max_daily_loss_fraction:
        return RiskDecision(False, "Daily loss limit reached.", available)
    if calculate_drawdown(equity, peak) >= max_drawdown_fraction:
        return RiskDecision(False, "Maximum drawdown limit reached.", available)
    if proposed > available + 1e-9:
        return RiskDecision(False, "Combined open-risk limit would be exceeded.", available)
    return RiskDecision(True, "Portfolio risk checks passed.", available)


def aggregate_currency_exposure(
    positions: Sequence[dict[str, float]],
) -> dict[str, float]:
    """Sum signed exposure by currency from simple currency/value records."""
    totals: dict[str, float] = {}
    for position in positions:
        currency = position.get("currency")
        amount = position.get("amount")
        if not isinstance(currency, str) or not currency.strip():
            raise ValueError("Each exposure requires a currency code.")
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            raise ValueError("Exposure amount must be finite.")
        value = float(amount)
        if not math.isfinite(value):
            raise ValueError("Exposure amount must be finite.")
        code = currency.strip().upper()
        totals[code] = totals.get(code, 0.0) + value
    return totals


def has_duplicate_pair(
    open_pairs: Sequence[tuple[str, str]], proposed_pair: tuple[str, str]
) -> bool:
    """Detect an already-open pair regardless of leg ordering."""
    proposed = frozenset(symbol.upper() for symbol in proposed_pair)
    if len(proposed) != 2:
        raise ValueError("A pair must contain two different symbols.")
    for pair in open_pairs:
        existing = frozenset(symbol.upper() for symbol in pair)
        if len(existing) != 2:
            raise ValueError("Open pairs must contain two different symbols.")
        if existing == proposed:
            return True
    return False
