"""Historical probability calculator for the Matryoshka scanner."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional

from core.config import ScannerConfig
from core.models import Candle, Direction
from core.signal_detector import check_signal_candle, compute_trade_params
from core.levels import level_touched
from core.indicators import atr as calc_atr, ema


@dataclass
class ProbabilityResult:
    wins: int = 0
    losses: int = 0
    unresolved: int = 0
    total: int = 0
    probability_pct: float = 0.0
    low_sample: bool = True


def _resolve_trade(
    candles: List[Candle],
    start_idx: int,
    direction: Direction,
    entry: float,
    sl: float,
    tp: float,
    max_bars: int,
) -> Optional[str]:
    for i in range(start_idx, min(start_idx + max_bars, len(candles))):
        c = candles[i]
        if direction == Direction.LONG:
            if c.low <= sl:
                return "loss"
            if c.high >= tp:
                return "win"
        else:
            if c.high >= sl:
                return "loss"
            if c.low <= tp:
                return "win"
    return None


def calculate_probability(
    symbol: str,
    h4_candles: List[Candle],
    d1_candles: List[Candle],
    levels: List[float],
    cfg: ScannerConfig,
) -> ProbabilityResult:
    result = ProbabilityResult()
    prob_cfg = cfg.probability
    atr_vals = calc_atr(h4_candles, 14)

    d1_ema = ema(d1_candles, cfg.context.ema_period) if d1_candles else []

    scan_end = len(h4_candles) - prob_cfg.max_bars_to_resolve - 1
    scan_start = max(20, len(h4_candles) - prob_cfg.lookback_bars)

    if scan_end <= scan_start:
        return result

    for i in range(scan_start, scan_end):
        candle = h4_candles[i]
        atr_val = atr_vals[i] if i < len(atr_vals) and not math.isnan(atr_vals[i]) else 0.0

        direction = _approximate_context(candle, d1_candles, d1_ema)
        if direction is None:
            continue

        touched_level: Optional[float] = None
        for lv in levels:
            if level_touched(
                candle,
                lv,
                mode=cfg.touch.mode,
                tolerance_value=cfg.touch.tolerance_value,
                tolerance_unit=cfg.touch.tolerance_unit,
                atr_value=atr_val,
            ):
                touched_level = lv
                break
        if touched_level is None:
            continue

        if not check_signal_candle(candle, direction, cfg):
            continue

        entry, sl, tp, _ = compute_trade_params(candle, direction, touched_level, atr_val, cfg)
        if entry == 0 or sl == entry:
            continue

        outcome = _resolve_trade(h4_candles, i + 1, direction, entry, sl, tp, prob_cfg.max_bars_to_resolve)
        result.total += 1
        if outcome == "win":
            result.wins += 1
        elif outcome == "loss":
            result.losses += 1
        else:
            result.unresolved += 1

    effective_wins = result.wins + result.unresolved * prob_cfg.unresolved_counts_as
    denom = result.wins + result.losses + result.unresolved
    if denom > 0:
        result.probability_pct = effective_wins / denom * 100.0
    result.low_sample = result.total < prob_cfg.min_sample_size
    return result


def _approximate_context(candle: Candle, d1_candles: List[Candle], d1_ema: List[float]) -> Optional[Direction]:
    if not d1_candles or not d1_ema:
        return None
    idx = None
    for j in range(len(d1_candles) - 1, -1, -1):
        if d1_candles[j].timestamp <= candle.timestamp:
            idx = j
            break
    if idx is None or idx >= len(d1_ema) or math.isnan(d1_ema[idx]):
        return None
    if d1_candles[idx].close > d1_ema[idx]:
        return Direction.LONG
    return Direction.SHORT
