"""Matryoshka strategy — rejection from key level with wick confirmation."""

from __future__ import annotations

import logging
import math
from typing import List, Optional

from core.config import ScannerConfig
from core.models import Candle, Direction, SignalCard
from core.indicators import ema, atr as calc_atr, candle_wick_ratio, close_position_check
from core.levels import get_manual_levels, level_touched, nearest_level, detect_swing_highs_lows, cluster_levels
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


class MatryoshkaStrategy(BaseStrategy):
    name = "matryoshka"

    def scan(
        self,
        symbol: str,
        d1_candles: List[Candle],
        h4_candles: List[Candle],
        cfg: ScannerConfig,
    ) -> Optional[SignalCard]:
        # Step 1 — context
        direction = self._context(d1_candles, cfg)
        if direction is None:
            logger.debug("[%s] %s: no context", self.name, symbol)
            return None

        # Levels
        levels = self._levels(symbol, h4_candles, cfg)
        if not levels:
            logger.debug("[%s] %s: no levels", self.name, symbol)
            return None

        if len(h4_candles) < 2:
            return None
        candle = h4_candles[-2]
        idx = len(h4_candles) - 2
        atr_val = self._atr(h4_candles, idx)

        # Touch
        touched = self._find_touched(candle, levels, direction, atr_val, cfg)
        if touched is None:
            logger.debug("[%s] %s: no level touched", self.name, symbol)
            return None

        # Trigger
        if not self._trigger(candle, direction, cfg):
            wr = candle_wick_ratio(candle, direction.value, cfg.trigger.wick_measure_mode)
            logger.debug("[%s] %s: trigger FAIL wick=%.2f", self.name, symbol, wr)
            return None

        # Trade params
        entry, sl, tp, ladder = self._trade_params(candle, direction, touched, atr_val, cfg)

        # Validate
        if entry == 0:
            return None
        sl_pct = abs(entry - sl) / entry * 100.0
        if sl_pct < cfg.validation.min_sl_distance_pct or sl_pct > cfg.validation.max_sl_distance_pct:
            logger.debug("[%s] %s: validation FAIL SL=%.3f%%", self.name, symbol, sl_pct)
            return None

        logger.info("[%s] %s: ✅ %s entry=%.6g SL=%.6g TP=%.6g",
                    self.name, symbol, direction.value, entry, sl, tp)

        return SignalCard(
            symbol=symbol,
            direction=direction,
            timeframe="H4",
            signal_candle_time=candle.timestamp,
            level_price=touched,
            entry_price=entry,
            stop_loss=sl,
            take_profit=tp,
            rr_target=cfg.take_profit.rr_target,
            probability_percent=0.0,
            sample_size_n=0,
            ladder=ladder,
            tradingview_link=self._tv_link(symbol),
            strategy_name=self.name,
        )

    # ------------------------------------------------------------------
    # Helpers (moved from signal_detector.py)
    # ------------------------------------------------------------------

    @staticmethod
    def _context(d1_candles: List[Candle], cfg: ScannerConfig) -> Optional[Direction]:
        ema_vals = ema(d1_candles, cfg.context.ema_period)
        if not d1_candles or math.isnan(ema_vals[-1]):
            return None
        return Direction.LONG if d1_candles[-1].close > ema_vals[-1] else Direction.SHORT

    @staticmethod
    def _levels(symbol: str, h4_candles: List[Candle], cfg: ScannerConfig) -> List[float]:
        if cfg.levels_mode == "manual":
            return get_manual_levels(cfg.levels_manual, symbol)
        raw = detect_swing_highs_lows(h4_candles, order=5)
        return cluster_levels(raw, tolerance_pct=0.5)

    @staticmethod
    def _atr(h4_candles: List[Candle], index: int) -> float:
        vals = calc_atr(h4_candles, 14)
        if index < len(vals) and not math.isnan(vals[index]):
            return vals[index]
        return 0.0

    @staticmethod
    def _find_touched(candle, levels, direction, atr_val, cfg) -> Optional[float]:
        for lv in levels:
            if level_touched(candle, lv,
                             mode=cfg.touch.mode,
                             tolerance_value=cfg.touch.tolerance_value,
                             tolerance_unit=cfg.touch.tolerance_unit,
                             atr_value=atr_val):
                return lv
        nl = nearest_level(candle, levels, direction.value)
        if nl is not None and level_touched(candle, nl,
                                            mode=cfg.touch.mode,
                                            tolerance_value=cfg.touch.tolerance_value,
                                            tolerance_unit=cfg.touch.tolerance_unit,
                                            atr_value=atr_val):
            return nl
        return None

    @staticmethod
    def _trigger(candle: Candle, direction: Direction, cfg: ScannerConfig) -> bool:
        if candle.body < cfg.trigger.min_body_size:
            return False
        ratio = candle_wick_ratio(candle, direction.value, cfg.trigger.wick_measure_mode)
        if ratio < cfg.trigger.min_wick_ratio:
            return False
        if not close_position_check(candle, direction.value, cfg.trigger.close_position_k):
            return False
        return True

    @staticmethod
    def _trade_params(candle, direction, level, atr_val, cfg):
        entry = candle.close
        mode = cfg.stop_loss.buffer_mode
        val = cfg.stop_loss.buffer_value
        if mode == "percent":
            buf = entry * val / 100.0
        elif mode == "atr":
            buf = atr_val * val
        else:
            buf = val

        if direction == Direction.LONG:
            sl = candle.low - buf
            risk = entry - sl
            tp = entry + cfg.take_profit.rr_target * risk
        else:
            sl = candle.high + buf
            risk = sl - entry
            tp = entry - cfg.take_profit.rr_target * risk

        ladder = []
        if cfg.take_profit.ladder_enabled and cfg.take_profit.ladder_steps:
            ladder = cfg.take_profit.ladder_steps
        return entry, sl, tp, ladder
