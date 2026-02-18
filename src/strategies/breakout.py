"""Breakout strategy — close above/below key level with volume confirmation.

Logic:
1. D1 context: EMA50 determines bias.
2. Auto-detect H4 swing levels.
3. Signal candle closes decisively beyond a level (body, not just wick).
4. Volume of signal candle > 1.5× average volume of last 20 candles.
5. Entry at candle close, SL just inside the broken level, TP at 2R.
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
VOL_MULT = 1.5
VOL_LOOKBACK = 20
SL_BUFFER_ATR_MULT = 0.2


class BreakoutStrategy(BaseStrategy):
    name = "breakout"

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

        # --- levels ---
        levels = resolve_levels(
            cfg.levels_manual,
            symbol,
            h4_candles,
            cfg,
            reference_price=h4_candles[-2].close,
        )
        if not levels:
            logger.debug("[%s] %s: no levels", self.name, symbol)
            return None

        candle = h4_candles[-2]
        idx = len(h4_candles) - 2
        atr_vals = calc_atr(h4_candles, 14)
        atr_val = atr_vals[idx] if idx < len(atr_vals) and not math.isnan(atr_vals[idx]) else 0.0
        if atr_val == 0:
            return None

        # --- volume check ---
        vol_start = max(0, idx - VOL_LOOKBACK)
        recent_vols = [c.volume for c in h4_candles[vol_start:idx] if c.volume > 0]
        if not recent_vols:
            return None
        avg_vol = sum(recent_vols) / len(recent_vols)
        if candle.volume < avg_vol * VOL_MULT:
            logger.debug("[%s] %s: volume %.0f < %.0f×%.1f",
                         self.name, symbol, candle.volume, avg_vol, VOL_MULT)
            return None

        # --- find broken level ---
        prev_candle = h4_candles[idx - 1] if idx > 0 else None
        broken_level: Optional[float] = None

        for lv in levels:
            if direction == Direction.LONG:
                # candle closes above level, previous candle closed below or at level
                if candle.close > lv and candle.open <= lv + atr_val * 0.1:
                    if prev_candle is None or prev_candle.close <= lv + atr_val * 0.1:
                        # body must be mostly above the level
                        if min(candle.open, candle.close) < lv + atr_val * 0.5:
                            broken_level = lv
                            break
            else:
                if candle.close < lv and candle.open >= lv - atr_val * 0.1:
                    if prev_candle is None or prev_candle.close >= lv - atr_val * 0.1:
                        if max(candle.open, candle.close) > lv - atr_val * 0.5:
                            broken_level = lv
                            break

        if broken_level is None:
            logger.debug("[%s] %s: no level broken", self.name, symbol)
            return None

        # --- trade params ---
        entry = candle.close
        buf = atr_val * SL_BUFFER_ATR_MULT

        if direction == Direction.LONG:
            sl = broken_level - buf
            risk = entry - sl
            tp = entry + RR_TARGET * risk
        else:
            sl = broken_level + buf
            risk = sl - entry
            tp = entry - RR_TARGET * risk

        if entry == 0 or risk <= 0:
            return None
        sl_pct = abs(entry - sl) / entry * 100.0
        if sl_pct < 0.1 or sl_pct > 10.0:
            return None

        logger.info("[%s] %s: ✅ %s entry=%.6g SL=%.6g TP=%.6g (level=%.6g, vol=%.0f/%.0f)",
                    self.name, symbol, direction.value, entry, sl, tp,
                    broken_level, candle.volume, avg_vol)

        return SignalCard(
            symbol=symbol,
            direction=direction,
            timeframe="H4",
            signal_candle_time=candle.timestamp,
            level_price=broken_level,
            entry_price=entry,
            stop_loss=sl,
            take_profit=tp,
            rr_target=RR_TARGET,
            probability_percent=0.0,
            sample_size_n=0,
            tradingview_link=self._tv_link(symbol),
            strategy_name=self.name,
        )
