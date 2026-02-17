"""EMA Bounce strategy — price pulls back to EMA 21 and bounces in trend direction.

Triggers much more frequently than Matryoshka because it doesn't require
a specific key level — the EMA itself acts as dynamic support/resistance.

Logic:
1. D1 context: price above EMA50 → LONG bias, below → SHORT bias.
2. H4 EMA21 acts as dynamic S/R.
3. Signal candle must touch or pierce EMA21 with its wick, then close
   back on the trend side.
4. Entry at signal candle close, SL beyond the wick, TP at 2R.
"""

from __future__ import annotations

import logging
import math
from typing import List, Optional

from core.config import ScannerConfig
from core.models import Candle, Direction, SignalCard
from core.indicators import ema, atr as calc_atr
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

EMA_FAST = 21
EMA_SLOW = 50
RR_TARGET = 2.0
SL_BUFFER_ATR_MULT = 0.3


class EMABounceStrategy(BaseStrategy):
    name = "ema_bounce"

    def scan(
        self,
        symbol: str,
        d1_candles: List[Candle],
        h4_candles: List[Candle],
        cfg: ScannerConfig,
    ) -> Optional[SignalCard]:
        # --- context from D1 ---
        d1_ema = ema(d1_candles, EMA_SLOW)
        if not d1_candles or math.isnan(d1_ema[-1]):
            logger.debug("[%s] %s: no D1 context", self.name, symbol)
            return None
        direction = Direction.LONG if d1_candles[-1].close > d1_ema[-1] else Direction.SHORT

        # --- H4 EMA21 ---
        if len(h4_candles) < EMA_FAST + 2:
            return None
        h4_ema21 = ema(h4_candles, EMA_FAST)
        atr_vals = calc_atr(h4_candles, 14)

        candle = h4_candles[-2]  # last closed
        idx = len(h4_candles) - 2
        ema_val = h4_ema21[idx]
        atr_val = atr_vals[idx] if idx < len(atr_vals) and not math.isnan(atr_vals[idx]) else 0.0

        if math.isnan(ema_val) or atr_val == 0:
            return None

        # --- touch check: wick must reach EMA21 zone ---
        touch_zone = atr_val * 0.3  # tolerance

        if direction == Direction.LONG:
            # candle low must dip into EMA21 zone, but close above EMA21
            if candle.low > ema_val + touch_zone:
                logger.debug("[%s] %s: LONG — low %.6g didn't reach EMA21 %.6g",
                             self.name, symbol, candle.low, ema_val)
                return None
            if candle.close < ema_val:
                logger.debug("[%s] %s: LONG — closed below EMA21", self.name, symbol)
                return None
            # must be bullish or at least close in upper half
            if candle.close < candle.open and candle.body > atr_val * 0.1:
                logger.debug("[%s] %s: LONG — bearish candle", self.name, symbol)
                return None
        else:
            # candle high must reach EMA21 zone, but close below EMA21
            if candle.high < ema_val - touch_zone:
                logger.debug("[%s] %s: SHORT — high %.6g didn't reach EMA21 %.6g",
                             self.name, symbol, candle.high, ema_val)
                return None
            if candle.close > ema_val:
                logger.debug("[%s] %s: SHORT — closed above EMA21", self.name, symbol)
                return None
            if candle.close > candle.open and candle.body > atr_val * 0.1:
                logger.debug("[%s] %s: SHORT — bullish candle", self.name, symbol)
                return None

        # --- trade params ---
        entry = candle.close
        buf = atr_val * SL_BUFFER_ATR_MULT

        if direction == Direction.LONG:
            sl = candle.low - buf
            risk = entry - sl
            tp = entry + RR_TARGET * risk
        else:
            sl = candle.high + buf
            risk = sl - entry
            tp = entry - RR_TARGET * risk

        # validate
        if entry == 0 or risk <= 0:
            return None
        sl_pct = abs(entry - sl) / entry * 100.0
        if sl_pct < 0.1 or sl_pct > 10.0:
            return None

        logger.info("[%s] %s: ✅ %s entry=%.6g SL=%.6g TP=%.6g (EMA21=%.6g)",
                    self.name, symbol, direction.value, entry, sl, tp, ema_val)

        return SignalCard(
            symbol=symbol,
            direction=direction,
            timeframe="H4",
            signal_candle_time=candle.timestamp,
            level_price=round(ema_val, 8),
            entry_price=entry,
            stop_loss=sl,
            take_profit=tp,
            rr_target=RR_TARGET,
            probability_percent=0.0,
            sample_size_n=0,
            tradingview_link=self._tv_link(symbol),
            strategy_name=self.name,
        )
