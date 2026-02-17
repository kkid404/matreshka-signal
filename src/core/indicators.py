"""Technical indicators used by the Matryoshka scanner."""

from __future__ import annotations

from typing import List

from core.models import Candle


def ema(candles: List[Candle], period: int) -> List[float]:
    closes = [c.close for c in candles]
    result: List[float] = [float("nan")] * len(closes)
    if len(closes) < period:
        return result

    sma = sum(closes[:period]) / period
    result[period - 1] = sma
    k = 2.0 / (period + 1)
    prev = sma
    for i in range(period, len(closes)):
        val = closes[i] * k + prev * (1 - k)
        result[i] = val
        prev = val
    return result


def atr(candles: List[Candle], period: int = 14) -> List[float]:
    if len(candles) < 2:
        return [float("nan")] * len(candles)

    tr_list: List[float] = [float("nan")]
    for i in range(1, len(candles)):
        prev_close = candles[i - 1].close
        c = candles[i]
        tr = max(c.high - c.low, abs(c.high - prev_close), abs(c.low - prev_close))
        tr_list.append(tr)

    result: List[float] = [float("nan")] * len(candles)
    if len(tr_list) < period + 1:
        return result

    first_atr = sum(tr_list[1 : period + 1]) / period
    result[period] = first_atr
    prev_atr = first_atr
    for i in range(period + 1, len(tr_list)):
        val = (prev_atr * (period - 1) + tr_list[i]) / period
        result[i] = val
        prev_atr = val
    return result


def candle_wick_ratio(candle: Candle, direction: str, mode: str) -> float:
    wick = candle.lower_wick if direction == "LONG" else candle.upper_wick

    if mode == "wick_vs_body":
        denom = candle.body if candle.body > 0 else 1e-12
    else:
        denom = candle.range if candle.range > 0 else 1e-12

    return wick / denom


def close_position_check(candle: Candle, direction: str, k: float) -> bool:
    rng = candle.range
    if rng == 0:
        return False
    if direction == "LONG":
        return candle.close >= candle.low + k * rng
    return candle.close <= candle.high - k * rng
