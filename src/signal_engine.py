"""Mean-reversion signal generation for validated cointegrated pairs."""

from dataclasses import dataclass
from enum import Enum
import math
from collections.abc import Sequence

from src.pair_discovery import PairCandidate
from src.statistics import calculate_spread, log_prices, z_score


class PositionSide(str, Enum):
    """Current simulated direction of the pair position."""

    NONE = "NONE"
    LONG_SPREAD = "LONG_SPREAD"
    SHORT_SPREAD = "SHORT_SPREAD"


class SignalAction(str, Enum):
    """Instruction for a later paper-execution component."""

    HOLD = "HOLD"
    ENTER_LONG_SPREAD = "ENTER_LONG_SPREAD"
    ENTER_SHORT_SPREAD = "ENTER_SHORT_SPREAD"
    EXIT = "EXIT"


@dataclass(frozen=True)
class TradingSignal:
    """A research signal; it never places or manages an actual order."""

    dependent_symbol: str
    independent_symbol: str
    action: SignalAction
    position: PositionSide
    z_score: float | None
    reason: str


def calculate_pair_z_score(
    candidate: PairCandidate,
    dependent_prices: Sequence[float],
    independent_prices: Sequence[float],
    window: int = 100,
) -> float:
    """Calculate the latest spread z-score using only the trailing window."""
    if window < 20:
        raise ValueError("Signal window must be at least 20 observations.")
    dependent = log_prices(dependent_prices)
    independent = log_prices(independent_prices)
    if len(dependent) != len(independent):
        raise ValueError("Pair price histories must have equal lengths.")
    if len(dependent) < window:
        raise ValueError("Insufficient price history for the signal window.")

    spread = calculate_spread(
        dependent[-window:],
        independent[-window:],
        candidate.hedge_ratio,
        candidate.intercept,
    )
    return z_score(spread)


def generate_signal(
    candidate: PairCandidate,
    dependent_prices: Sequence[float],
    independent_prices: Sequence[float],
    *,
    window: int = 100,
    entry_z: float = 2.0,
    exit_z: float = 0.5,
    stop_z: float = 3.0,
    current_position: PositionSide = PositionSide.NONE,
    cooldown_remaining: int = 0,
) -> TradingSignal:
    """Generate one deterministic signal without executing a trade.

    Entry is triggered by an extreme spread z-score. Existing positions exit
    near the mean or at the stop threshold. Cooldown only blocks new entries.
    """
    if not all(math.isfinite(value) for value in (entry_z, exit_z, stop_z)):
        raise ValueError("Signal thresholds must be finite.")
    if not 0 < exit_z < entry_z < stop_z:
        raise ValueError("Thresholds must satisfy 0 < exit < entry < stop.")
    if not isinstance(current_position, PositionSide):
        raise ValueError("Current position must be a PositionSide value.")
    if not isinstance(cooldown_remaining, int) or cooldown_remaining < 0:
        raise ValueError("Cooldown remaining must be a non-negative integer.")

    z_value = calculate_pair_z_score(
        candidate, dependent_prices, independent_prices, window
    )

    def result(action: SignalAction, reason: str) -> TradingSignal:
        return TradingSignal(
            dependent_symbol=candidate.dependent_symbol,
            independent_symbol=candidate.independent_symbol,
            action=action,
            position=current_position,
            z_score=z_value,
            reason=reason,
        )

    if current_position is PositionSide.LONG_SPREAD:
        if z_value <= -stop_z:
            return result(SignalAction.EXIT, "Long-spread stop threshold reached.")
        if z_value >= -exit_z:
            return result(SignalAction.EXIT, "Long-spread mean-reversion target reached.")
        return result(SignalAction.HOLD, "Long-spread position remains within limits.")

    if current_position is PositionSide.SHORT_SPREAD:
        if z_value >= stop_z:
            return result(SignalAction.EXIT, "Short-spread stop threshold reached.")
        if z_value <= exit_z:
            return result(SignalAction.EXIT, "Short-spread mean-reversion target reached.")
        return result(SignalAction.HOLD, "Short-spread position remains within limits.")

    if cooldown_remaining:
        return result(SignalAction.HOLD, "Entry blocked during post-trade cooldown.")
    if z_value <= -entry_z:
        return result(
            SignalAction.ENTER_LONG_SPREAD,
            "Spread is below the negative entry threshold.",
        )
    if z_value >= entry_z:
        return result(
            SignalAction.ENTER_SHORT_SPREAD,
            "Spread is above the positive entry threshold.",
        )
    return result(SignalAction.HOLD, "Spread has not reached an entry threshold.")
