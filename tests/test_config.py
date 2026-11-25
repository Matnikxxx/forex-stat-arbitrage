from src import config


def test_system_is_paper_only():
    assert config.TRADING_MODE == "PAPER"
    config.validate_settings()


def test_initial_capital_and_risk_limits():
    assert config.STARTING_CAPITAL_USD == 1_000.0
    assert config.MAX_RISK_PER_TRADE == 0.01
    assert config.MAX_SIMULTANEOUS_POSITIONS == 2


def test_initial_currency_universe():
    assert len(config.CURRENCY_PAIRS) == 4
    assert len(set(config.CURRENCY_PAIRS)) == 4
    assert set(config.SUPPORTED_CURRENCIES) == {"EUR", "GBP", "AUD", "USD", "JPY"}
