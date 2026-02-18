"""Data models for the Matryoshka scanner."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List


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
    strategy_name: str = "matryoshka"
    entry_min_price: float = 0.0
    entry_max_price: float = 0.0

    def __post_init__(self) -> None:
        if self.entry_price <= 0:
            return

        if self.entry_min_price > 0 and self.entry_max_price > 0:
            if self.entry_min_price > self.entry_max_price:
                self.entry_min_price, self.entry_max_price = self.entry_max_price, self.entry_min_price
            return

        risk = abs(self.entry_price - self.stop_loss)
        if risk <= 0:
            self.entry_min_price = self.entry_price
            self.entry_max_price = self.entry_price
            return

        # Acceptable entry zone: no more than 25% of initial stop distance from planned entry.
        zone_risk_part = risk * 0.25
        if self.direction == Direction.LONG:
            self.entry_min_price = max(self.entry_price - zone_risk_part, 0.0)
            self.entry_max_price = self.entry_price
        else:
            self.entry_min_price = self.entry_price
            self.entry_max_price = self.entry_price + zone_risk_part

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "direction": self.direction.value,
            "timeframe": self.timeframe,
            "signal_candle_time": self.signal_candle_time.isoformat(),
            "level_price": self.level_price,
            "entry_price": round(self.entry_price, 8),
            "entry_min_price": round(self.entry_min_price, 8),
            "entry_max_price": round(self.entry_max_price, 8),
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
            "strategy_name": self.strategy_name,
            "tradingview_link": self.tradingview_link,
        }
