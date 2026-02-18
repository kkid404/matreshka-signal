"""Engulfing strategy — bullish/bearish engulfing pattern near a key level.

Logic:
1. D1 context via EMA50.
2. Auto-detect H4 swing levels.
3. The last closed candle fully engulfs the previous candle's body.
4. The engulfing candle must be near a key level (within 1 ATR).
5. Direction of engulfing must match D1 bias.
6. Entry at engulfing candle close, SL beyond the pattern, TP at 2R.
"""

from __future__ import annotations

import logging
import math
from typing import List, Optional

from core.config import ScannerConfig
from core.models import Candle, Direction, SignalCard
from core.indicators import ema, atr as calc_atr
from core.levels import resolve_levels
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

RR_TARGET = 2.0
SL_BUFFER_ATR_MULT = 0.3
LEVEL_PROXIMITY_ATR = 1.5


class EngulfingStrategy(BaseStrategy):
    name = "engulfing"

    def scan(
        self,
        symbol: str,
        d1_candles: List[Candle],
        h4_candles: List[Candle],
        cfg: ScannerConfig,
    ) -> Optional[SignalCard]:
        # --- context ---
        d1_ema = ema(d1_candles, 50)
        if not d1_candles or math.isnan(d1_ema[-1]):
            return None
        direction = Direction.LONG if d1_candles[-1].close > d1_ema[-1] else Direction.SHORT

        if len(h4_candles) < 30:
            return None

        # We need at least 2 closed candles: [-3] = prev, [-2] = engulfing
        if len(h4_candles) < 3:
            return None

        eng = h4_candles[-2]   # engulfing candle (last closed)
        prev = h4_candles[-3]  # candle before it
        idx = len(h4_candles) - 2

        atr_vals = calc_atr(h4_candles, 14)
        atr_val = atr_vals[idx] if idx < len(atr_vals) and not math.isnan(atr_vals[idx]) else 0.0
        if atr_val == 0:
            return None

        # --- engulfing pattern check ---
        eng_body_top = max(eng.open, eng.close)
        eng_body_bot = min(eng.open, eng.close)
        prev_body_top = max(prev.open, prev.close)
        prev_body_bot = min(prev.open, prev.close)

        # Engulfing: current body fully covers previous body
        if not (eng_body_top > prev_body_top and eng_body_bot < prev_body_bot):
            logger.debug("[%s] %s: no engulfing pattern", self.name, symbol)
            return None

        # Direction must match bias
        if direction == Direction.LONG and not eng.is_bullish:
            logger.debug("[%s] %s: bearish engulfing in LONG context", self.name, symbol)
            return None
        if direction == Direction.SHORT and eng.is_bullish:
            logger.debug("[%s] %s: bullish engulfing in SHORT context", self.name, symbol)
            return None

        # Minimum body size (avoid tiny engulfings)
        if eng.body < atr_val * 0.3:
            logger.debug("[%s] %s: engulfing body too small %.6g < %.6g",
                         self.name, symbol, eng.body, atr_val * 0.3)
            return None

        # --- level proximity ---
        levels = resolve_levels(
            cfg.levels_manual,
            symbol,
            h4_candles,
            cfg,
            reference_price=eng.close,
        )
        if not levels:
            logger.debug("[%s] %s: no levels", self.name, symbol)
            return None

        near_level: Optional[float] = None
        for lv in levels:
            dist = abs(eng.close - lv)
            if dist < atr_val * LEVEL_PROXIMITY_ATR:
                near_level = lv
                break

        if near_level is None:
            logger.debug("[%s] %s: engulfing not near any level", self.name, symbol)
            return None

        # --- trade params ---
        entry = eng.close
        buf = atr_val * SL_BUFFER_ATR_MULT

        if direction == Direction.LONG:
            sl = min(eng.low, prev.low) - buf
            risk = entry - sl
            tp = entry + RR_TARGET * risk
        else:
            sl = max(eng.high, prev.high) + buf
            risk = sl - entry
            tp = entry - RR_TARGET * risk

        if entry == 0 or risk <= 0:
            return None
        sl_pct = abs(entry - sl) / entry * 100.0
        if sl_pct < 0.1 or sl_pct > 10.0:
            return None

        logger.info("[%s] %s: ✅ %s entry=%.6g SL=%.6g TP=%.6g (level=%.6g)",
                    self.name, symbol, direction.value, entry, sl, tp, near_level)

        return SignalCard(
            symbol=symbol,
            direction=direction,
            timeframe="H4",
            signal_candle_time=eng.timestamp,
            level_price=near_level,
            entry_price=entry,
            stop_loss=sl,
            take_profit=tp,
            rr_target=RR_TARGET,
            probability_percent=0.0,
            sample_size_n=0,
            tradingview_link=self._tv_link(symbol),
            strategy_name=self.name,
        )
