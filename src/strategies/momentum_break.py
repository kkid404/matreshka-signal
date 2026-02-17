"""Momentum Break strategy — frequent continuation setup.

Logic:
1. D1 context via EMA50 (trend filter).
2. H4 signal candle closes beyond the previous N-candle range in trend direction.
3. Signal candle should also be on the trend side of H4 EMA21.
4. Entry at close, SL behind signal candle with ATR buffer, TP at 1.8R.
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

LOOKBACK = 5
RR_TARGET = 1.8
SL_BUFFER_ATR_MULT = 0.2


class MomentumBreakStrategy(BaseStrategy):
    name = "momentum_break"

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

        if len(h4_candles) < max(LOOKBACK + 2, 30):
            return None

        idx = len(h4_candles) - 2
        candle = h4_candles[idx]
        prev_slice = h4_candles[idx - LOOKBACK:idx]

        ema21 = ema(h4_candles, 21)
        ema_val = ema21[idx]
        if math.isnan(ema_val):
            return None

        atr_vals = calc_atr(h4_candles, 14)
        atr_val = atr_vals[idx] if idx < len(atr_vals) and not math.isnan(atr_vals[idx]) else 0.0
        if atr_val <= 0:
            return None

        range_high = max(c.high for c in prev_slice)
        range_low = min(c.low for c in prev_slice)

        if direction == Direction.LONG:
            if candle.close <= range_high or candle.close < ema_val:
                return None
            entry = candle.close
            sl = candle.low - atr_val * SL_BUFFER_ATR_MULT
            risk = entry - sl
            tp = entry + RR_TARGET * risk
            level = range_high
        else:
            if candle.close >= range_low or candle.close > ema_val:
                return None
            entry = candle.close
            sl = candle.high + atr_val * SL_BUFFER_ATR_MULT
            risk = sl - entry
            tp = entry - RR_TARGET * risk
            level = range_low

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
            level_price=level,
            entry_price=entry,
            stop_loss=sl,
            take_profit=tp,
            rr_target=RR_TARGET,
            probability_percent=0.0,
            sample_size_n=0,
            tradingview_link=self._tv_link(symbol),
            strategy_name=self.name,
        )
