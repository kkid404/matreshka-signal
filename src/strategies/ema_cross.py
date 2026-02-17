"""EMA Cross strategy — frequent trend-following entries.

Logic:
1. D1 context via EMA50.
2. On H4, detect fresh EMA9/EMA21 crossover in direction of context.
3. Require signal candle close on trend side of EMA21.
4. Entry at close, SL beyond signal candle with ATR buffer, TP at 1.6R.
"""

from __future__ import annotations

import logging
import math
from typing import List, Optional

from core.config import ScannerConfig
from core.indicators import atr as calc_atr, ema
from core.models import Candle, Direction, SignalCard
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

FAST_EMA = 9
SLOW_EMA = 21
RR_TARGET = 1.6
SL_BUFFER_ATR_MULT = 0.25


class EMACrossStrategy(BaseStrategy):
    name = "ema_cross"

    def scan(
        self,
        symbol: str,
        d1_candles: List[Candle],
        h4_candles: List[Candle],
        cfg: ScannerConfig,
    ) -> Optional[SignalCard]:
        d1_ema = ema(d1_candles, 50)
        if not d1_candles or math.isnan(d1_ema[-1]):
            return None
        direction = Direction.LONG if d1_candles[-1].close > d1_ema[-1] else Direction.SHORT

        if len(h4_candles) < max(SLOW_EMA + 3, 30):
            return None

        idx = len(h4_candles) - 2
        candle = h4_candles[idx]

        ema_fast = ema(h4_candles, FAST_EMA)
        ema_slow = ema(h4_candles, SLOW_EMA)

        if math.isnan(ema_fast[idx]) or math.isnan(ema_slow[idx]):
            return None

        prev_idx = idx - 1
        if prev_idx < 0:
            return None

        crossed_long = ema_fast[prev_idx] <= ema_slow[prev_idx] and ema_fast[idx] > ema_slow[idx]
        crossed_short = ema_fast[prev_idx] >= ema_slow[prev_idx] and ema_fast[idx] < ema_slow[idx]

        if direction == Direction.LONG:
            if not crossed_long or candle.close < ema_slow[idx]:
                return None
        else:
            if not crossed_short or candle.close > ema_slow[idx]:
                return None

        atr_vals = calc_atr(h4_candles, 14)
        atr_val = atr_vals[idx] if idx < len(atr_vals) and not math.isnan(atr_vals[idx]) else 0.0
        if atr_val <= 0:
            return None

        entry = candle.close
        if direction == Direction.LONG:
            sl = candle.low - atr_val * SL_BUFFER_ATR_MULT
            risk = entry - sl
            tp = entry + RR_TARGET * risk
            level = ema_slow[idx]
        else:
            sl = candle.high + atr_val * SL_BUFFER_ATR_MULT
            risk = sl - entry
            tp = entry - RR_TARGET * risk
            level = ema_slow[idx]

        if entry == 0 or risk <= 0:
            return None

        sl_pct = abs(entry - sl) / entry * 100.0
        if sl_pct < 0.08 or sl_pct > 8.0:
            return None

        logger.info(
            "[%s] %s: ✅ %s entry=%.6g SL=%.6g TP=%.6g",
            self.name,
            symbol,
            direction.value,
            entry,
            sl,
            tp,
        )

        return SignalCard(
            symbol=symbol,
            direction=direction,
            timeframe="H4",
            signal_candle_time=candle.timestamp,
            level_price=round(level, 8),
            entry_price=entry,
            stop_loss=sl,
            take_profit=tp,
            rr_target=RR_TARGET,
            probability_percent=0.0,
            sample_size_n=0,
            tradingview_link=self._tv_link(symbol),
            strategy_name=self.name,
        )
