# Forex Statistical Arbitrage

A free-first, paper-trading-only Forex statistical arbitrage research system.

## Initial scope
- Currency universe: EUR/USD, GBP/USD, AUD/USD, USD/JPY.
- Pair selection: automatic discovery plus manual selection.
- Starting simulated capital: USD 1,000.
- Maximum risk per paired trade: 1% of simulated equity.
- Maximum simultaneous positions: 2.
- Dashboard: Streamlit.
- Supported development environments: Windows + VS Code and GitHub Codespaces.

## Safety
This project is paper-trading only. It must not connect to a broker for live order placement, request withdrawal permissions, or handle real-money execution.

## Development
Use Python 3.12 or newer in the 3.12 series.

```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS/Linux/Codespaces:
# source .venv/bin/activate

python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Run tests with:

```bash
python -m pytest -q
```

Market-data providers and their free-tier limits will be evaluated before any provider is selected. No paid service is required by the initial scaffold.
