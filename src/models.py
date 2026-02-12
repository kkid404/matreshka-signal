"""Data models for the Matryoshka scanner."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional


class Direction(Enum):
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        return min(self.open, self.close) - self.low

    @property
    def is_bullish(self) -> bool:
        return self.close >= self.open


@dataclass
class LadderStep:
    tp_rr: float
    close_pct: float
    move_sl_to_be: bool = False


@dataclass
class SignalCard:
    symbol: str
    direction: Direction
    timeframe: str
    signal_candle_time: datetime
    level_price: float
    entry_price: float
    stop_loss: float
    take_profit: float
    rr_target: float
    probability_percent: float
    sample_size_n: int
    ladder: List[LadderStep] = field(default_factory=list)
    tradingview_link: str = ""
    low_sample: bool = False

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "direction": self.direction.value,
            "timeframe": self.timeframe,
            "signal_candle_time": self.signal_candle_time.isoformat(),
            "level_price": self.level_price,
            "entry_price": round(self.entry_price, 8),
            "stop_loss": round(self.stop_loss, 8),
            "take_profit": round(self.take_profit, 8),
            "rr_target": self.rr_target,
            "probability_percent": round(self.probability_percent, 1),
            "sample_size_N": self.sample_size_n,
            "low_sample": self.low_sample,
            "ladder": [
                {"tp_rr": s.tp_rr, "close_pct": s.close_pct, "move_sl_to_be": s.move_sl_to_be}
                for s in self.ladder
            ],
            "tradingview_link": self.tradingview_link,
        }
