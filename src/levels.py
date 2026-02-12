"""Level detection and touch logic for the Matryoshka scanner."""

from __future__ import annotations

import math
from typing import List, Optional

from models import Candle
from indicators import atr as calc_atr


def get_manual_levels(levels_dict: dict, symbol: str) -> List[float]:
    """Return manually defined levels for a symbol."""
    return sorted(levels_dict.get(symbol, []))


# ---------------------------------------------------------------------------
# Touch detection
# ---------------------------------------------------------------------------

def level_touched(
    candle: Candle,
    level: float,
    mode: str,
    tolerance_value: float = 0.3,
    tolerance_unit: str = "percent",
    atr_value: float = 0.0,
) -> bool:
    """Check if *candle* touches *level*.

    mode:
        'range_touch' — level is between candle low and high
        'tolerance_touch' — candle close is within tolerance of level
    """
    if mode == "range_touch":
        return candle.low <= level <= candle.high

    # tolerance_touch
    if tolerance_unit == "percent":
        tol = level * tolerance_value / 100.0
    else:  # atr
        tol = atr_value * tolerance_value
    return abs(candle.close - level) <= tol


def nearest_level(
    candle: Candle,
    levels: List[float],
    direction: str,
) -> Optional[float]:
    """Return the nearest level that the candle is interacting with.

    For LONG we look for support levels (level <= candle close).
    For SHORT we look for resistance levels (level >= candle close).
    """
    candidates: List[float] = []
    for lv in levels:
        if direction == "LONG" and lv <= candle.high:
            candidates.append(lv)
        elif direction == "SHORT" and lv >= candle.low:
            candidates.append(lv)
    if not candidates:
        return None
    # Closest to current close
    return min(candidates, key=lambda lv: abs(lv - candle.close))


# ---------------------------------------------------------------------------
# Auto-levels (v2 roadmap)
# ---------------------------------------------------------------------------

def detect_swing_highs_lows(
    candles: List[Candle], order: int = 5
) -> List[float]:
    """Find fractal swing highs and swing lows.

    A swing high at index *i* means candles[i].high is the highest
    among candles[i-order .. i+order].  Likewise for swing lows.
    """
    levels: List[float] = []
    for i in range(order, len(candles) - order):
        high_is_peak = all(
            candles[i].high >= candles[i + j].high for j in range(-order, order + 1) if j != 0
        )
        low_is_trough = all(
            candles[i].low <= candles[i + j].low for j in range(-order, order + 1) if j != 0
        )
        if high_is_peak:
            levels.append(candles[i].high)
        if low_is_trough:
            levels.append(candles[i].low)
    return levels


def cluster_levels(levels: List[float], tolerance_pct: float = 0.5) -> List[float]:
    """Cluster nearby price levels and return their midpoints."""
    if not levels:
        return []
    sorted_lvls = sorted(levels)
    clusters: List[List[float]] = [[sorted_lvls[0]]]
    for lv in sorted_lvls[1:]:
        if abs(lv - clusters[-1][-1]) / clusters[-1][-1] * 100 <= tolerance_pct:
            clusters[-1].append(lv)
        else:
            clusters.append([lv])
    return [sum(c) / len(c) for c in clusters]
