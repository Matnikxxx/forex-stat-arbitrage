"""Central, safe defaults for the paper-trading prototype."""

TRADING_MODE = "PAPER"
STARTING_CAPITAL_USD = 1_000.0
MAX_RISK_PER_TRADE = 0.01
MAX_SIMULTANEOUS_POSITIONS = 2

CURRENCY_PAIRS = (
    "EUR/USD",
    "GBP/USD",
    "AUD/USD",
    "USD/JPY",
)

SUPPORTED_CURRENCIES = ("EUR", "GBP", "AUD", "USD", "JPY")


def validate_settings() -> None:
    """Raise ValueError if core settings are invalid."""
    if TRADING_MODE != "PAPER":
        raise ValueError("This project must remain in PAPER mode.")
    if STARTING_CAPITAL_USD <= 0:
        raise ValueError("Starting simulated capital must be positive.")
    if not 0 < MAX_RISK_PER_TRADE <= 0.01:
        raise ValueError(
            "Risk per paired trade must be greater than 0 and at most 1%."
        )
    if MAX_SIMULTANEOUS_POSITIONS < 1:
        raise ValueError("At least one simultaneous position must be allowed.")
    if len(CURRENCY_PAIRS) != 4 or len(set(CURRENCY_PAIRS)) != 4:
        raise ValueError(
            "The initial currency universe must contain four unique pairs."
        )
