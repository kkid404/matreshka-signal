"""Core signal detection logic for the Matryoshka scanner."""

from __future__ import annotations

import logging
import math
from typing import List, Optional, Tuple

from config import ScannerConfig
from models import Candle, Direction, LadderStep, SignalCard
from indicators import ema, atr as calc_atr, candle_wick_ratio, close_position_check
from levels import get_manual_levels, level_touched, nearest_level, detect_swing_highs_lows, cluster_levels

logger = logging.getLogger(__name__)


def determine_context(
    d1_candles: List[Candle],
    cfg: ScannerConfig,
) -> Optional[Direction]:
    """Step 1 — determine directional bias from D1 EMA."""
    period = cfg.context.ema_period
    ema_values = ema(d1_candles, period)
    if not d1_candles or math.isnan(ema_values[-1]):
        return None
    last_close = d1_candles[-1].close
    if last_close > ema_values[-1]:
        return Direction.LONG
    else:
        return Direction.SHORT


def _get_levels_for_symbol(
    symbol: str,
    h4_candles: List[Candle],
    cfg: ScannerConfig,
) -> List[float]:
    """Return price levels depending on mode (manual / auto)."""
    if cfg.levels_mode == "manual":
        return get_manual_levels(cfg.levels_manual, symbol)
    # Auto levels (v2)
    raw = detect_swing_highs_lows(h4_candles, order=5)
    return cluster_levels(raw, tolerance_pct=0.5)


def _compute_atr_value(h4_candles: List[Candle], index: int) -> float:
    """ATR(14) value at given index."""
    atr_vals = calc_atr(h4_candles, 14)
    if index < len(atr_vals) and not math.isnan(atr_vals[index]):
        return atr_vals[index]
    return 0.0


def _compute_buffer(
    price: float,
    atr_value: float,
    cfg: ScannerConfig,
) -> float:
    """Compute SL buffer based on config."""
    mode = cfg.stop_loss.buffer_mode
    val = cfg.stop_loss.buffer_value
    if mode == "percent":
        return price * val / 100.0
    elif mode == "atr":
        return atr_value * val
    else:  # fixed
        return val


def check_signal_candle(
    candle: Candle,
    direction: Direction,
    cfg: ScannerConfig,
) -> bool:
    """Step 3 — check if candle qualifies as a trigger (rejection candle)."""
    dir_str = direction.value

    # Minimum body size
    if candle.body < cfg.trigger.min_body_size:
        return False

    # Wick ratio
    ratio = candle_wick_ratio(candle, dir_str, cfg.trigger.wick_measure_mode)
    if ratio < cfg.trigger.min_wick_ratio:
        return False

    # Close position
    if not close_position_check(candle, dir_str, cfg.trigger.close_position_k):
        return False

    return True


def compute_trade_params(
    signal_candle: Candle,
    direction: Direction,
    level: float,
    atr_value: float,
    cfg: ScannerConfig,
) -> Tuple[float, float, float, List[LadderStep]]:
    """Step 4 — compute entry, SL, TP, ladder.

    Returns (entry_price, stop_loss, take_profit, ladder).
    """
    entry = signal_candle.close  # approximation; ideally next candle open
    buf = _compute_buffer(entry, atr_value, cfg)

    if direction == Direction.LONG:
        sl = signal_candle.low - buf
        risk = entry - sl
        tp = entry + cfg.take_profit.rr_target * risk
    else:
        sl = signal_candle.high + buf
        risk = sl - entry
        tp = entry - cfg.take_profit.rr_target * risk

    ladder: List[LadderStep] = []
    if cfg.take_profit.ladder_enabled and cfg.take_profit.ladder_steps:
        ladder = cfg.take_profit.ladder_steps

    return entry, sl, tp, ladder


def validate_signal(
    entry: float,
    sl: float,
    tp: float,
    cfg: ScannerConfig,
) -> bool:
    """Step 5 — sanity checks."""
    if entry == 0:
        return False
    sl_dist_pct = abs(entry - sl) / entry * 100.0
    if sl_dist_pct < cfg.validation.min_sl_distance_pct:
        return False
    if sl_dist_pct > cfg.validation.max_sl_distance_pct:
        return False
    return True


def scan_symbol(
    symbol: str,
    d1_candles: List[Candle],
    h4_candles: List[Candle],
    cfg: ScannerConfig,
) -> Optional[SignalCard]:
    """Run the full Matryoshka detection pipeline for one symbol.

    Returns a SignalCard if a valid signal is found, else None.
    """
    # Step 1 — context
    direction = determine_context(d1_candles, cfg)
    if direction is None:
        logger.debug("%s: no context (EMA not ready)", symbol)
        return None
    logger.debug("%s: context = %s", symbol, direction.value)

    # Levels
    levels = _get_levels_for_symbol(symbol, h4_candles, cfg)
    if not levels:
        logger.debug("%s: no levels defined", symbol)
        return None
    logger.debug("%s: %d levels found", symbol, len(levels))

    # Step 2 + 3 — check the last *closed* H4 candle
    if len(h4_candles) < 2:
        return None
    signal_candle = h4_candles[-2]  # last closed candle ([-1] may still be forming)
    idx = len(h4_candles) - 2

    atr_val = _compute_atr_value(h4_candles, idx)

    # Find a touched level
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
        # Also try nearest_level heuristic
        nl = nearest_level(signal_candle, levels, direction.value)
        if nl is not None and level_touched(
            signal_candle, nl,
            mode=cfg.touch.mode,
            tolerance_value=cfg.touch.tolerance_value,
            tolerance_unit=cfg.touch.tolerance_unit,
            atr_value=atr_val,
        ):
            touched_level = nl

    if touched_level is None:
        logger.debug("%s: no level touched (candle L=%.6g H=%.6g C=%.6g)", symbol,
                     signal_candle.low, signal_candle.high, signal_candle.close)
        return None
    logger.debug("%s: touched level %.6g", symbol, touched_level)

    # Step 3 — trigger
    if not check_signal_candle(signal_candle, direction, cfg):
        wick_r = candle_wick_ratio(signal_candle, direction.value, cfg.trigger.wick_measure_mode)
        logger.debug("%s: trigger FAIL — wick_ratio=%.2f (need>=%.2f), body=%.6g",
                     symbol, wick_r, cfg.trigger.min_wick_ratio, signal_candle.body)
        return None
    logger.debug("%s: trigger OK", symbol)

    # Step 4 — trade params
    entry, sl, tp, ladder = compute_trade_params(
        signal_candle, direction, touched_level, atr_val, cfg,
    )

    # Step 5 — validate
    sl_dist = abs(entry - sl) / entry * 100.0
    if not validate_signal(entry, sl, tp, cfg):
        logger.debug("%s: validation FAIL — SL dist=%.3f%% (need %.3f–%.3f%%)",
                     symbol, sl_dist, cfg.validation.min_sl_distance_pct,
                     cfg.validation.max_sl_distance_pct)
        return None
    logger.info("%s: ✅ SIGNAL FOUND — %s entry=%.6g SL=%.6g TP=%.6g",
                symbol, direction.value, entry, sl, tp)

    # Build TV link
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
        rr_target=cfg.take_profit.rr_target,
        probability_percent=0.0,  # filled later
        sample_size_n=0,
        ladder=ladder,
        tradingview_link=tv_link,
    )
    return card
