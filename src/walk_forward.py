"""Chronological walk-forward validation for pair strategies."""

from dataclasses import dataclass
import math
from collections.abc import Sequence

from src.backtesting import BacktestConfig, BacktestResult, run_pair_backtest
from src.pair_discovery import PairCandidate, evaluate_pair


@dataclass(frozen=True)
class WalkForwardFold:
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    candidate: PairCandidate
    result: BacktestResult


@dataclass(frozen=True)
class WalkForwardResult:
    folds: tuple[WalkForwardFold, ...]
    tested_folds: int
    skipped_folds: int
    starting_capital: float
    ending_equity: float
    total_return: float
    max_drawdown: float
    win_rate: float
    profit_factor: float
    expectancy: float


def _validate_inputs(
    dependent: Sequence[float],
    independent: Sequence[float],
    training_window: int,
    testing_window: int,
    config: BacktestConfig,
) -> tuple[list[float], list[float]]:
    y = [float(value) for value in dependent]
    x = [float(value) for value in independent]
    if len(y) != len(x):
        raise ValueError("Paired histories must have equal lengths.")
    if isinstance(training_window, bool) or not isinstance(training_window, int):
        raise ValueError("Training window must be an integer.")
    if isinstance(testing_window, bool) or not isinstance(testing_window, int):
        raise ValueError("Testing window must be an integer.")
    if training_window < 100:
        raise ValueError("Training window must be at least 100 observations.")
    if len(y) < training_window + testing_window:
        raise ValueError("Insufficient data for one complete walk-forward fold.")
    if any(not math.isfinite(value) or value <= 0 for value in y + x):
        raise ValueError("Prices must be finite and positive.")
    if testing_window < config.window + 2:
        raise ValueError("Testing window must exceed the signal window.")
    return y, x


def run_walk_forward(
    dependent_symbol: str,
    independent_symbol: str,
    dependent: Sequence[float],
    independent: Sequence[float],
    *,
    training_window: int = 500,
    testing_window: int = 100,
    config: BacktestConfig = BacktestConfig(),
    max_pvalue: float = 0.05,
    min_correlation: float = 0.5,
) -> WalkForwardResult:
    """Fit each pair on past data and evaluate only the immediately following block."""
    y, x = _validate_inputs(
        dependent, independent, training_window, testing_window, config
    )
    if not dependent_symbol or not independent_symbol:
        raise ValueError("Both currency pair symbols are required.")
    if dependent_symbol == independent_symbol:
        raise ValueError("Pair symbols must be different.")
    if not 0 < max_pvalue < 1 or not 0 <= min_correlation <= 1:
        raise ValueError("Pair discovery thresholds are invalid.")

    folds: list[WalkForwardFold] = []
    skipped = 0
    for test_start in range(training_window, len(y), testing_window):
        test_end = min(test_start + testing_window, len(y))
        if test_end - test_start < config.window + 2:
            break
        train_start = test_start - training_window
        try:
            candidate = evaluate_pair(
                dependent_symbol,
                independent_symbol,
                y[train_start:test_start],
                x[train_start:test_start],
                min_observations=100,
                max_pvalue=max_pvalue,
                min_correlation=min_correlation,
            )
        except (ValueError, ArithmeticError):
            candidate = None
        if candidate is None:
            skipped += 1
            continue
        result = run_pair_backtest(
            candidate,
            y[test_start:test_end],
            x[test_start:test_end],
            config,
        )
        folds.append(WalkForwardFold(
            train_start, test_start, test_start, test_end, candidate, result
        ))

    starting = float(config.starting_capital)
    equity = starting
    all_trades = []
    peak = equity
    max_drawdown = 0.0
    for fold in folds:
        fold_pnl = fold.result.ending_equity - fold.result.starting_capital
        scale = equity / fold.result.starting_capital
        scaled_pnl = fold_pnl * scale
        equity += scaled_pnl
        for trade in fold.result.trades:
            all_trades.append(trade)
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak)

    wins = [trade.net_pnl for trade in all_trades if trade.net_pnl > 0]
    losses = [trade.net_pnl for trade in all_trades if trade.net_pnl < 0]
    gross_loss = abs(sum(losses))
    gross_profit = sum(wins)
    profit_factor = (
        gross_profit / gross_loss if gross_loss else
        math.inf if gross_profit else 0.0
    )
    trade_count = len(all_trades)
    return WalkForwardResult(
        folds=tuple(folds),
        tested_folds=len(folds),
        skipped_folds=skipped,
        starting_capital=starting,
        ending_equity=equity,
        total_return=equity / starting - 1.0,
        max_drawdown=max_drawdown,
        win_rate=len(wins) / trade_count if trade_count else 0.0,
        profit_factor=profit_factor,
        expectancy=sum(trade.net_pnl for trade in all_trades) / trade_count
        if trade_count else 0.0,
    )
