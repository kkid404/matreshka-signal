"""Core signal detection logic for the Matryoshka scanner."""

from __future__ import annotations

import logging
import math
from typing import List, Optional, Tuple

from core.config import ScannerConfig
from core.ladder import normalize_ladder_steps, resolve_rr_target
from core.models import Candle, Direction, LadderStep, SignalCard
from core.indicators import ema, atr as calc_atr, candle_wick_ratio, close_position_check
from core.levels import get_manual_levels, level_touched, nearest_level, detect_swing_highs_lows, cluster_levels

logger = logging.getLogger(__name__)


def determine_context(d1_candles: List[Candle], cfg: ScannerConfig) -> Optional[Direction]:
    period = cfg.context.ema_period
    ema_values = ema(d1_candles, period)
    if not d1_candles or math.isnan(ema_values[-1]):
        return None
    last_close = d1_candles[-1].close
    if last_close > ema_values[-1]:
        return Direction.LONG
    return Direction.SHORT


def _get_levels_for_symbol(symbol: str, h4_candles: List[Candle], cfg: ScannerConfig) -> List[float]:
    if cfg.levels_mode == "manual":
        return get_manual_levels(cfg.levels_manual, symbol)
    raw = detect_swing_highs_lows(h4_candles, order=5)
    return cluster_levels(raw, tolerance_pct=0.5)


def _compute_atr_value(h4_candles: List[Candle], index: int) -> float:
    atr_vals = calc_atr(h4_candles, 14)
    if index < len(atr_vals) and not math.isnan(atr_vals[index]):
        return atr_vals[index]
    return 0.0


def _compute_buffer(price: float, atr_value: float, cfg: ScannerConfig) -> float:
    mode = cfg.stop_loss.buffer_mode
    val = cfg.stop_loss.buffer_value
    if mode == "percent":
        return price * val / 100.0
    if mode == "atr":
        return atr_value * val
    return val


def check_signal_candle(candle: Candle, direction: Direction, cfg: ScannerConfig) -> bool:
    dir_str = direction.value

    if candle.body < cfg.trigger.min_body_size:
        return False

    ratio = candle_wick_ratio(candle, dir_str, cfg.trigger.wick_measure_mode)
    if ratio < cfg.trigger.min_wick_ratio:
        return False

    if not close_position_check(candle, dir_str, cfg.trigger.close_position_k):
        return False

    return True


def compute_trade_params(
    signal_candle: Candle,
    direction: Direction,
    level: float,
    atr_value: float,
    cfg: ScannerConfig,
) -> Tuple[float, float, float, List[LadderStep], float]:
    entry = signal_candle.close
    buf = _compute_buffer(entry, atr_value, cfg)

    ladder: List[LadderStep] = []
    if cfg.take_profit.ladder_enabled and cfg.take_profit.ladder_steps:
        ladder = normalize_ladder_steps(cfg.take_profit.ladder_steps)

    rr_target = resolve_rr_target(cfg.take_profit.rr_target, ladder)

    if direction == Direction.LONG:
        sl = signal_candle.low - buf
        risk = entry - sl
        tp = entry + rr_target * risk
    else:
        sl = signal_candle.high + buf
        risk = sl - entry
        tp = entry - rr_target * risk

    return entry, sl, tp, ladder, rr_target


def validate_signal(entry: float, sl: float, tp: float, cfg: ScannerConfig, atr_value: float = 0.0) -> bool:
    if entry <= 0:
        return False

    # Directional realism for TP.
    if tp == entry:
        return False

    sl_dist_pct = abs(entry - sl) / entry * 100.0
    if sl_dist_pct < cfg.validation.min_sl_distance_pct:
        return False
    if sl_dist_pct > cfg.validation.max_sl_distance_pct:
        return False

    tp_dist_pct = abs(tp - entry) / entry * 100.0
    if tp_dist_pct > cfg.validation.max_tp_distance_pct:
        return False

    # Optional ATR-based realism filters.
    if atr_value > 0:
        sl_atr = abs(entry - sl) / atr_value
        if sl_atr < cfg.validation.min_sl_atr_multiple:
            return False
        if sl_atr > cfg.validation.max_sl_atr_multiple:
            return False

        tp_atr = abs(tp - entry) / atr_value
        if tp_atr > cfg.validation.max_tp_atr_multiple:
            return False

    return True


def scan_symbol(
    symbol: str,
    d1_candles: List[Candle],
    h4_candles: List[Candle],
    cfg: ScannerConfig,
) -> Optional[SignalCard]:
    direction = determine_context(d1_candles, cfg)
    if direction is None:
        logger.debug("%s: no context (EMA not ready)", symbol)
        return None
    logger.debug("%s: context = %s", symbol, direction.value)

    levels = _get_levels_for_symbol(symbol, h4_candles, cfg)
    if not levels:
        logger.debug("%s: no levels defined", symbol)
        return None
    logger.debug("%s: %d levels found", symbol, len(levels))

    if len(h4_candles) < 2:
        return None
    signal_candle = h4_candles[-2]
    idx = len(h4_candles) - 2

    atr_val = _compute_atr_value(h4_candles, idx)

    touched_level: Optional[float] = None
    for lv in levels:
        if level_touched(
            signal_candle,
            lv,
            mode=cfg.touch.mode,
            tolerance_value=cfg.touch.tolerance_value,
            tolerance_unit=cfg.touch.tolerance_unit,
            atr_value=atr_val,
        ):
            touched_level = lv
            break

    if touched_level is None:
        nl = nearest_level(signal_candle, levels, direction.value)
        if nl is not None and level_touched(
            signal_candle,
            nl,
            mode=cfg.touch.mode,
            tolerance_value=cfg.touch.tolerance_value,
            tolerance_unit=cfg.touch.tolerance_unit,
            atr_value=atr_val,
        ):
            touched_level = nl

    if touched_level is None:
        logger.debug(
            "%s: no level touched (candle L=%.6g H=%.6g C=%.6g)",
            symbol,
            signal_candle.low,
            signal_candle.high,
            signal_candle.close,
        )
        return None
    logger.debug("%s: touched level %.6g", symbol, touched_level)

    if not check_signal_candle(signal_candle, direction, cfg):
        wick_r = candle_wick_ratio(signal_candle, direction.value, cfg.trigger.wick_measure_mode)
        logger.debug(
            "%s: trigger FAIL — wick_ratio=%.2f (need>=%.2f), body=%.6g",
            symbol,
            wick_r,
            cfg.trigger.min_wick_ratio,
            signal_candle.body,
        )
        return None
    logger.debug("%s: trigger OK", symbol)

    entry, sl, tp, ladder, rr_target = compute_trade_params(signal_candle, direction, touched_level, atr_val, cfg)

    sl_dist = abs(entry - sl) / entry * 100.0
    if not validate_signal(entry, sl, tp, cfg, atr_value=atr_val):
        logger.debug(
            "%s: validation FAIL — SL dist=%.3f%% (need %.3f–%.3f%%)",
            symbol,
            sl_dist,
            cfg.validation.min_sl_distance_pct,
            cfg.validation.max_sl_distance_pct,
        )
        return None
    logger.info("%s: ✅ SIGNAL FOUND — %s entry=%.6g SL=%.6g TP=%.6g", symbol, direction.value, entry, sl, tp)

    base_sym = symbol.replace("USDT", "")
    tv_link = f"https://www.tradingview.com/chart/?symbol=BYBIT:{base_sym}USDT.P"

    card = SignalCard(
        symbol=symbol,
        direction=direction,
        timeframe="H4",
        signal_candle_time=signal_candle.timestamp,
        level_price=touched_level,
        entry_price=entry,
        stop_loss=sl,
        take_profit=tp,
        rr_target=rr_target,
        probability_percent=0.0,
        sample_size_n=0,
        ladder=ladder,
        tradingview_link=tv_link,
    )
    return card
