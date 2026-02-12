"""Historical probability calculator for the Matryoshka scanner."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

from config import ScannerConfig
from models import Candle, Direction
from signal_detector import check_signal_candle, compute_trade_params, determine_context
from levels import level_touched, get_manual_levels, detect_swing_highs_lows, cluster_levels
from indicators import atr as calc_atr, ema

logger = logging.getLogger(__name__)


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
    """Simulate forward from *start_idx* to see if TP or SL is hit first.

    Returns 'win', 'loss', or None (unresolved).
    """
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
    """Scan historical H4 candles for matching signals and backtest them.

    Returns aggregated win/loss statistics.
    """
    result = ProbabilityResult()
    prob_cfg = cfg.probability
    atr_vals = calc_atr(h4_candles, 14)

    # Pre-compute D1 EMA for context (we'll do a rough mapping)
    d1_ema = ema(d1_candles, cfg.context.ema_period) if d1_candles else []

    # We need at least some bars to look forward
    scan_end = len(h4_candles) - prob_cfg.max_bars_to_resolve - 1
    scan_start = max(20, len(h4_candles) - prob_cfg.lookback_bars)

    if scan_end <= scan_start:
        return result

    for i in range(scan_start, scan_end):
        candle = h4_candles[i]
        atr_val = atr_vals[i] if i < len(atr_vals) and not math.isnan(atr_vals[i]) else 0.0

        # Determine context direction using D1 data up to candle timestamp
        direction = _approximate_context(candle, d1_candles, d1_ema)
        if direction is None:
            continue

        # Check level touch
        touched_level: Optional[float] = None
        for lv in levels:
            if level_touched(
                candle, lv,
                mode=cfg.touch.mode,
                tolerance_value=cfg.touch.tolerance_value,
                tolerance_unit=cfg.touch.tolerance_unit,
                atr_value=atr_val,
            ):
                touched_level = lv
                break
        if touched_level is None:
            continue

        # Check trigger
        if not check_signal_candle(candle, direction, cfg):
            continue

        # Compute trade params
        entry, sl, tp, _ = compute_trade_params(candle, direction, touched_level, atr_val, cfg)
        if entry == 0 or sl == entry:
            continue

        # Resolve forward
        outcome = _resolve_trade(
            h4_candles, i + 1, direction, entry, sl, tp,
            prob_cfg.max_bars_to_resolve,
        )
        result.total += 1
        if outcome == "win":
            result.wins += 1
        elif outcome == "loss":
            result.losses += 1
        else:
            result.unresolved += 1

    # Compute probability
    effective_wins = result.wins + result.unresolved * prob_cfg.unresolved_counts_as
    denom = result.wins + result.losses + result.unresolved
    if denom > 0:
        result.probability_pct = effective_wins / denom * 100.0
    result.low_sample = result.total < prob_cfg.min_sample_size
    return result


def _approximate_context(
    candle: Candle,
    d1_candles: List[Candle],
    d1_ema: List[float],
) -> Optional[Direction]:
    """Find the D1 EMA context that was valid at the time of *candle*."""
    if not d1_candles or not d1_ema:
        return None
    # Find last D1 candle with timestamp <= candle.timestamp
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
