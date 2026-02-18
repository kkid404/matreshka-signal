from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from core.models import Direction, LadderStep, SignalCard


def signal_card_from_dict(data: Dict[str, Any]) -> SignalCard:
    """Build SignalCard from JSON-friendly dict payload."""
    ladder_steps: List[LadderStep] = []
    for item in data.get("ladder", []) or []:
        ladder_steps.append(
            LadderStep(
                tp_rr=float(item.get("tp_rr", 0.0)),
                close_pct=float(item.get("close_pct", 0.0)),
                move_sl_to_be=bool(item.get("move_sl_to_be", False)),
            )
        )

    raw_time = str(data.get("signal_candle_time", ""))
    if raw_time.endswith("Z"):
        raw_time = raw_time[:-1] + "+00:00"

    sample_size = data.get("sample_size_n", data.get("sample_size_N", 0))

    return SignalCard(
        symbol=str(data.get("symbol", "")),
        direction=Direction(str(data.get("direction", "LONG"))),
        timeframe=str(data.get("timeframe", "H4")),
        signal_candle_time=datetime.fromisoformat(raw_time),
        level_price=float(data.get("level_price", 0.0)),
        entry_price=float(data.get("entry_price", 0.0)),
        stop_loss=float(data.get("stop_loss", 0.0)),
        take_profit=float(data.get("take_profit", 0.0)),
        rr_target=float(data.get("rr_target", 0.0)),
        probability_percent=float(data.get("probability_percent", 0.0)),
        sample_size_n=int(sample_size),
        ladder=ladder_steps,
        tradingview_link=str(data.get("tradingview_link", "")),
        low_sample=bool(data.get("low_sample", False)),
        strategy_name=str(data.get("strategy_name", "matryoshka")),
        entry_min_price=float(data.get("entry_min_price", 0.0)),
        entry_max_price=float(data.get("entry_max_price", 0.0)),
    )
