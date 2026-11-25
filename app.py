"""Initial Streamlit dashboard shell. No trading logic is connected yet."""

import streamlit as st

from src.config import (
    CURRENCY_PAIRS,
    MAX_RISK_PER_TRADE,
    MAX_SIMULTANEOUS_POSITIONS,
    STARTING_CAPITAL_USD,
    TRADING_MODE,
    validate_settings,
)

validate_settings()

st.set_page_config(page_title="Forex Statistical Arbitrage", layout="wide")
st.title("Forex Statistical Arbitrage")
st.caption("Research and paper-trading dashboard — no live trading.")

left, middle, right = st.columns(3)
left.metric("Simulated starting capital", f"${STARTING_CAPITAL_USD:,.2f}")
middle.metric("Maximum risk per paired trade", f"{MAX_RISK_PER_TRADE:.0%}")
right.metric("Maximum open positions", MAX_SIMULTANEOUS_POSITIONS)

st.subheader("Initial currency universe")
st.write(", ".join(CURRENCY_PAIRS))

st.info(
    f"System mode: {TRADING_MODE}. Market-data connections, strategy signals, "
    "and simulated execution will be added and tested in later phases."
)
