"""Level detection and touch logic for the Matryoshka scanner."""

from __future__ import annotations

from typing import List, Optional

from core.models import Candle


def get_manual_levels(levels_dict: dict, symbol: str) -> List[float]:
    return sorted(levels_dict.get(symbol, []))


def level_touched(
    candle: Candle,
    level: float,
    mode: str,
    tolerance_value: float = 0.3,
    tolerance_unit: str = "percent",
    atr_value: float = 0.0,
) -> bool:
    if mode == "range_touch":
        return candle.low <= level <= candle.high

    if tolerance_unit == "percent":
        tol = level * tolerance_value / 100.0
    else:
        tol = atr_value * tolerance_value
    return abs(candle.close - level) <= tol


def nearest_level(candle: Candle, levels: List[float], direction: str) -> Optional[float]:
    candidates: List[float] = []
    for lv in levels:
        if direction == "LONG" and lv <= candle.high:
            candidates.append(lv)
        elif direction == "SHORT" and lv >= candle.low:
            candidates.append(lv)
    if not candidates:
        return None
    return min(candidates, key=lambda lv: abs(lv - candle.close))


def detect_swing_highs_lows(candles: List[Candle], order: int = 5) -> List[float]:
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
