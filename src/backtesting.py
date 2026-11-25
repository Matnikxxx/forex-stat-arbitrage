"""Cost-aware, forward-only historical backtesting for one currency pair."""

from dataclasses import dataclass
import math
from collections.abc import Sequence

from src.pair_discovery import PairCandidate
from src.statistics import calculate_spread, log_prices, maximum_drawdown


@dataclass(frozen=True)
class BacktestConfig:
    starting_capital: float = 1000.0
    window: int = 100
    entry_z: float = 2.0
    exit_z: float = 0.5
    stop_z: float = 3.0
    units_a: int = 1000
    units_b: int = 1000
    fee_bps: float = 0.0
    slippage_bps: float = 0.0


@dataclass(frozen=True)
class BacktestTrade:
    direction: str
    entry_index: int
    exit_index: int
    entry_a: float
    entry_b: float
    exit_a: float
    exit_b: float
    gross_pnl: float
    fees: float
    slippage_cost: float
    net_pnl: float
    exit_reason: str


@dataclass(frozen=True)
class BacktestResult:
    starting_capital: float
    ending_equity: float
    total_return: float
    trades: tuple[BacktestTrade, ...]
    equity_curve: tuple[float, ...]
    max_drawdown: float
    win_rate: float
    profit_factor: float
    expectancy: float
    average_trade: float


def validate_backtest_inputs(
    dependent: Sequence[float], independent: Sequence[float],
    config: BacktestConfig,
) -> tuple[list[float], list[float]]:
    """Validate paired prices and all strategy/cost settings."""
    y = [float(value) for value in dependent]
    x = [float(value) for value in independent]
    if len(y) != len(x) or len(y) < config.window + 2:
        raise ValueError("Paired histories must match and exceed the signal window.")
    if any(not math.isfinite(v) or v <= 0 for v in y + x):
        raise ValueError("Backtest prices must be finite and positive.")
    if not math.isfinite(config.starting_capital) or config.starting_capital <= 0:
        raise ValueError("Starting capital must be finite and positive.")
    if isinstance(config.window, bool) or not isinstance(config.window, int) or config.window < 20:
        raise ValueError("Backtest window must be an integer of at least 20.")
    if not 0 < config.exit_z < config.entry_z < config.stop_z:
        raise ValueError("Z-score thresholds must satisfy 0 < exit < entry < stop.")
    if any(isinstance(v, bool) or not isinstance(v, int) or v <= 0
           for v in (config.units_a, config.units_b)):
        raise ValueError("Both leg sizes must be positive integers.")
    for name, value in (("Fee", config.fee_bps), ("Slippage", config.slippage_bps)):
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} basis points must be finite and non-negative.")
    return y, x


def calculate_spread_z_score(
    dependent: Sequence[float], independent: Sequence[float],
    candidate: PairCandidate, window: int,
) -> float:
    """Calculate a z-score using only the trailing observations available now."""
    y = log_prices(dependent[-window:])
    x = log_prices(independent[-window:])
    spread = calculate_spread(y, x, candidate.hedge_ratio, candidate.intercept)
    mean = sum(spread) / len(spread)
    variance = sum((value - mean) ** 2 for value in spread) / len(spread)
    if variance <= 0 or not math.isfinite(variance):
        raise ValueError("Spread z-score is undefined for a constant window.")
    return (spread[-1] - mean) / math.sqrt(variance)


def calculate_round_trip_cost(
    price_a: float, price_b: float, units_a: int, units_b: int,
    basis_points: float,
) -> float:
    """Calculate one-side proportional cost across both legs."""
    if not math.isfinite(basis_points) or basis_points < 0:
        raise ValueError("Basis points must be finite and non-negative.")
    notional = price_a * units_a + price_b * units_b
    return notional * basis_points / 10000.0


def _trade_pnl(
    direction: str, entry_a: float, entry_b: float, exit_a: float, exit_b: float,
    units_a: int, units_b: int,
) -> float:
    if direction == "LONG_SPREAD":
        return (exit_a - entry_a) * units_a + (entry_b - exit_b) * units_b
    return (entry_a - exit_a) * units_a + (exit_b - entry_b) * units_b


def calculate_backtest_metrics(
    starting_capital: float, trades: Sequence[BacktestTrade],
    equity_curve: Sequence[float],
) -> BacktestResult:
    """Summarise returns, drawdown, win rate, profit factor and expectancy."""
    ending = float(equity_curve[-1])
    pnl = [trade.net_pnl for trade in trades]
    wins = [value for value in pnl if value > 0]
    losses = [value for value in pnl if value < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss else (
        math.inf if gross_profit else 0.0
    )
    return BacktestResult(
        starting_capital=starting_capital,
        ending_equity=ending,
        total_return=(ending / starting_capital) - 1.0,
        trades=tuple(trades),
        equity_curve=tuple(float(value) for value in equity_curve),
        max_drawdown=maximum_drawdown(equity_curve),
        win_rate=len(wins) / len(pnl) if pnl else 0.0,
        profit_factor=profit_factor,
        expectancy=sum(pnl) / len(pnl) if pnl else 0.0,
        average_trade=sum(pnl) / len(pnl) if pnl else 0.0,
    )


def run_pair_backtest(
    candidate: PairCandidate, dependent: Sequence[float],
    independent: Sequence[float], config: BacktestConfig = BacktestConfig(),
) -> BacktestResult:
    """Run a single-position backtest; signals execute on the following bar.

    Costs are charged on both entry and exit. The final open trade is closed
    at the last available close. This is a research simulation, not a forecast.
    """
    y, x = validate_backtest_inputs(dependent, independent, config)
    trades: list[BacktestTrade] = []
    equity_curve = [float(config.starting_capital)]
    realized = 0.0
    position = None

    for signal_index in range(config.window - 1, len(y) - 1):
        z_value = calculate_spread_z_score(
            y[: signal_index + 1], x[: signal_index + 1], candidate, config.window
        )
        if position is None:
            direction = (
                "LONG_SPREAD" if z_value <= -config.entry_z else
                "SHORT_SPREAD" if z_value >= config.entry_z else None
            )
            if direction is not None:
                fill_index = signal_index + 1
                entry_a, entry_b = y[fill_index], x[fill_index]
                fee = calculate_round_trip_cost(
                    entry_a, entry_b, config.units_a, config.units_b, config.fee_bps
                )
                slip = calculate_round_trip_cost(
                    entry_a, entry_b, config.units_a, config.units_b,
                    config.slippage_bps,
                )
                position = {
                    "direction": direction, "index": fill_index,
                    "a": entry_a, "b": entry_b, "entry_cost": fee + slip,
                    "fee": fee, "slip": slip,
                }
        else:
            direction = position["direction"]
            exit_reason = None
            if direction == "LONG_SPREAD":
                if z_value <= -config.stop_z:
                    exit_reason = "STOP"
                elif z_value >= -config.exit_z:
                    exit_reason = "MEAN_REVERSION"
            else:
                if z_value >= config.stop_z:
                    exit_reason = "STOP"
                elif z_value <= config.exit_z:
                    exit_reason = "MEAN_REVERSION"
            if exit_reason:
                fill_index = signal_index + 1
                exit_a, exit_b = y[fill_index], x[fill_index]
                gross = _trade_pnl(
                    direction, position["a"], position["b"], exit_a, exit_b,
                    config.units_a, config.units_b,
                )
                exit_fee = calculate_round_trip_cost(
                    exit_a, exit_b, config.units_a, config.units_b, config.fee_bps
                )
                exit_slip = calculate_round_trip_cost(
                    exit_a, exit_b, config.units_a, config.units_b,
                    config.slippage_bps,
                )
                fees = position["fee"] + exit_fee
                slippage = position["slip"] + exit_slip
                net = gross - fees - slippage
                trades.append(BacktestTrade(
                    direction, position["index"], fill_index,
                    position["a"], position["b"], exit_a, exit_b,
                    gross, fees, slippage, net, exit_reason,
                ))
                realized += net
                position = None
        equity_curve.append(config.starting_capital + realized)

    if position is not None:
        exit_index = len(y) - 1
        exit_a, exit_b = y[exit_index], x[exit_index]
        gross = _trade_pnl(
            position["direction"], position["a"], position["b"], exit_a, exit_b,
            config.units_a, config.units_b,
        )
        exit_fee = calculate_round_trip_cost(
            exit_a, exit_b, config.units_a, config.units_b, config.fee_bps
        )
        exit_slip = calculate_round_trip_cost(
            exit_a, exit_b, config.units_a, config.units_b, config.slippage_bps
        )
        fees = position["fee"] + exit_fee
        slippage = position["slip"] + exit_slip
        net = gross - fees - slippage
        trades.append(BacktestTrade(
            position["direction"], position["index"], exit_index,
            position["a"], position["b"], exit_a, exit_b,
            gross, fees, slippage, net, "END_OF_DATA",
        ))
        realized += net
        equity_curve[-1] = config.starting_capital + realized

    return calculate_backtest_metrics(config.starting_capital, trades, equity_curve)
