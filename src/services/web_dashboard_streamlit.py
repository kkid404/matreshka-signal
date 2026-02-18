from __future__ import annotations

import os
from collections import Counter
from typing import List

import pandas as pd
import streamlit as st

from core.models import SignalCard
from infrastructure.signal_engine_client import SignalEngineClient


def _cards_to_rows(cards: List[SignalCard]) -> List[dict]:
    rows: List[dict] = []
    for c in cards:
        rows.append(
            {
                "symbol": c.symbol,
                "strategy": c.strategy_name,
                "direction": c.direction.value,
                "timeframe": c.timeframe,
                "signal_time_utc": c.signal_candle_time.strftime("%Y-%m-%d %H:%M"),
                "entry": round(c.entry_price, 8),
                "entry_zone": f"{c.entry_min_price:.6g} - {c.entry_max_price:.6g}",
                "stop_loss": round(c.stop_loss, 8),
                "take_profit": round(c.take_profit, 8),
                "rr": c.rr_target,
                "probability_pct": round(c.probability_percent, 2),
                "sample_size": c.sample_size_n,
                "tv_link": c.tradingview_link,
            }
        )
    return rows


def _show_metrics(cards: List[SignalCard], strategies_payload: dict) -> None:
    directions = Counter(c.direction.value for c in cards)
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Signals", len(cards))
    col2.metric("LONG", directions.get("LONG", 0))
    col3.metric("SHORT", directions.get("SHORT", 0))
    col4.metric("Strategies ON", len(strategies_payload.get("enabled", [])))


def main() -> None:
    st.set_page_config(page_title="Matryoshka Dashboard", page_icon="📊", layout="wide")

    default_engine_url = os.getenv("SIGNAL_ENGINE_SERVICE_URL", "http://127.0.0.1:8082")

    st.title("📊 Matryoshka Web Dashboard")
    st.caption("MVP: scan/replay signals via signal-engine-service")

    with st.sidebar:
        st.subheader("Connection")
        engine_url = st.text_input("Signal Engine URL", value=default_engine_url)
        st.markdown("---")
        st.subheader("Replay Params")
        symbol = st.text_input("Symbol", value="BTCUSDT")
        lookback = st.number_input("Lookback (H4)", min_value=200, max_value=5000, value=1200, step=100)

    client = SignalEngineClient(base_url=engine_url)

    try:
        strategies_payload = client.strategies()
    except Exception as exc:
        st.error(f"Cannot load strategies: {exc}")
        strategies_payload = {"ok": False, "enabled": []}

    left, right = st.columns([1, 1])
    with left:
        run_scan = st.button("▶ Run Scan", use_container_width=True)
    with right:
        run_replay = st.button("↻ Run Replay", use_container_width=True)

    cards: List[SignalCard] = []
    mode = None

    if run_scan:
        mode = "scan"
        cards = client.scan_run()
    elif run_replay:
        mode = "replay"
        cards = client.replay_run(symbol=symbol.strip().upper(), lookback=int(lookback))

    if mode is None:
        st.info("Нажми `Run Scan` или `Run Replay`, чтобы получить сигналы.")
        if strategies_payload.get("ok"):
            st.write("Активные стратегии:", ", ".join(strategies_payload.get("enabled", [])) or "—")
        return

    _show_metrics(cards, strategies_payload)

    if not cards:
        st.warning("Сигналы не найдены или сервис временно недоступен.")
        return

    rows = _cards_to_rows(cards)
    df = pd.DataFrame(rows)

    st.subheader(f"Results: {mode}")
    st.dataframe(df, use_container_width=True)


if __name__ == "__main__":
    main()
