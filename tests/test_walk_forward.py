"""Tests for chronological walk-forward validation."""

import pytest

from src.backtesting import BacktestConfig, BacktestResult
from src.pair_discovery import PairCandidate
from src.walk_forward import run_walk_forward


def prices(length=700):
    first = []
    second = []
    for index in range(length):
        base = 1.1 + index * 0.00001
        first.append(base + 0.001 * ((index % 17) - 8) / 8)
        second.append(base)
    return first, second


def fake_candidate(*args, **kwargs):
    return PairCandidate("EUR/USD", "GBP/USD", 0.9, 0.01, 1.0, 0.0,
                         5.0, 500, 0.9, 0.8)


def fake_backtest(candidate, y, x, config):
    equity = config.starting_capital + 10.0
    return BacktestResult(
        config.starting_capital, equity, 0.01, (), (config.starting_capital, equity),
        0.0, 0.0, 0.0, 0.0, 0.0,
    )


def test_walk_forward_uses_disjoint_chronological_folds(monkeypatch):
    import src.walk_forward as module
    monkeypatch.setattr(module, "evaluate_pair", fake_candidate)
    monkeypatch.setattr(module, "run_pair_backtest", fake_backtest)
    y, x = prices()
    result = run_walk_forward("EUR/USD", "GBP/USD", y, x,
                              training_window=300, testing_window=100,
                              config=BacktestConfig(window=30))
    assert result.tested_folds == 4
    assert result.folds[0].train_end == result.folds[0].test_start
    assert result.folds[0].test_end == result.folds[1].test_start


def test_walk_forward_never_trains_on_test_data(monkeypatch):
    import src.walk_forward as module
    observed = []
    def capture(symbol_a, symbol_b, a, b, **kwargs):
        observed.append((len(a), len(b)))
        return fake_candidate()
    monkeypatch.setattr(module, "evaluate_pair", capture)
    monkeypatch.setattr(module, "run_pair_backtest", fake_backtest)
    y, x = prices(500)
    run_walk_forward("EUR/USD", "GBP/USD", y, x, training_window=300,
                     testing_window=100, config=BacktestConfig(window=30))
    assert observed == [(300, 300), (300, 300)]


def test_walk_forward_compounds_fold_returns(monkeypatch):
    import src.walk_forward as module
    monkeypatch.setattr(module, "evaluate_pair", fake_candidate)
    monkeypatch.setattr(module, "run_pair_backtest", fake_backtest)
    y, x = prices(500)
    result = run_walk_forward("EUR/USD", "GBP/USD", y, x, training_window=300,
                              testing_window=100, config=BacktestConfig(window=30))
    assert result.ending_equity == pytest.approx(1020.1)


def test_walk_forward_skips_pairs_not_discovered(monkeypatch):
    import src.walk_forward as module
    monkeypatch.setattr(module, "evaluate_pair", lambda *args, **kwargs: None)
    y, x = prices(500)
    result = run_walk_forward("EUR/USD", "GBP/USD", y, x, training_window=300,
                              testing_window=100, config=BacktestConfig(window=30))
    assert result.tested_folds == 0
    assert result.skipped_folds == 2
    assert result.ending_equity == 1000


@pytest.mark.parametrize("kwargs", [
    {"training_window": 99},
    {"testing_window": 20},
])
def test_walk_forward_rejects_short_windows(kwargs):
    y, x = prices(500)
    with pytest.raises(ValueError):
        run_walk_forward("EUR/USD", "GBP/USD", y, x,
                         config=BacktestConfig(window=30), **kwargs)


def test_walk_forward_rejects_mismatched_histories():
    y, x = prices()
    with pytest.raises(ValueError, match="equal lengths"):
        run_walk_forward("EUR/USD", "GBP/USD", y, x[:-1])


def test_walk_forward_rejects_insufficient_history():
    y, x = prices(200)
    with pytest.raises(ValueError, match="Insufficient"):
        run_walk_forward("EUR/USD", "GBP/USD", y, x)


def test_walk_forward_rejects_invalid_prices():
    y, x = prices()
    y[0] = 0
    with pytest.raises(ValueError, match="finite and positive"):
        run_walk_forward("EUR/USD", "GBP/USD", y, x)


@pytest.mark.parametrize("symbols", [("EUR/USD", "EUR/USD"), ("", "GBP/USD")])
def test_walk_forward_rejects_invalid_symbols(symbols):
    y, x = prices()
    with pytest.raises(ValueError):
        run_walk_forward(*symbols, y, x)


def test_walk_forward_reports_returns_and_fold_count(monkeypatch):
    import src.walk_forward as module
    monkeypatch.setattr(module, "evaluate_pair", fake_candidate)
    monkeypatch.setattr(module, "run_pair_backtest", fake_backtest)
    y, x = prices(500)
    result = run_walk_forward("EUR/USD", "GBP/USD", y, x, training_window=300,
                              testing_window=100, config=BacktestConfig(window=30))
    assert result.total_return == pytest.approx(0.0201)
    assert result.tested_folds == 2
