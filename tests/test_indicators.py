"""Unit tests for indicators module."""

import math
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from datetime import datetime, timezone
from models import Candle
from indicators import ema, atr, candle_wick_ratio, close_position_check


def _make_candle(o, h, l, c, v=100.0, ts=None):
    if ts is None:
        ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return Candle(timestamp=ts, open=o, high=h, low=l, close=c, volume=v)


# ---------------------------------------------------------------------------
# EMA
# ---------------------------------------------------------------------------

class TestEMA:
    def test_ema_length(self):
        candles = [_make_candle(i, i + 1, i - 1, i) for i in range(1, 21)]
        result = ema(candles, 10)
        assert len(result) == 20

    def test_ema_first_values_nan(self):
        candles = [_make_candle(i, i + 1, i - 1, i) for i in range(1, 21)]
        result = ema(candles, 10)
        for i in range(9):
            assert math.isnan(result[i])
        assert not math.isnan(result[9])

    def test_ema_seed_is_sma(self):
        closes = list(range(1, 11))
        candles = [_make_candle(c, c + 1, c - 1, c) for c in closes]
        result = ema(candles, 10)
        expected_sma = sum(closes) / 10
        assert abs(result[9] - expected_sma) < 1e-9

    def test_ema_too_few_candles(self):
        candles = [_make_candle(1, 2, 0, 1)] * 3
        result = ema(candles, 10)
        assert all(math.isnan(v) for v in result)


# ---------------------------------------------------------------------------
# ATR
# ---------------------------------------------------------------------------

class TestATR:
    def test_atr_length(self):
        candles = [_make_candle(i, i + 2, i - 2, i + 1) for i in range(1, 31)]
        result = atr(candles, 14)
        assert len(result) == 30

    def test_atr_initial_nan(self):
        candles = [_make_candle(i, i + 2, i - 2, i + 1) for i in range(1, 31)]
        result = atr(candles, 14)
        for i in range(14):
            assert math.isnan(result[i])
        assert not math.isnan(result[14])

    def test_atr_positive(self):
        candles = [_make_candle(100, 105, 95, 102) for _ in range(30)]
        result = atr(candles, 14)
        for v in result[14:]:
            assert v > 0


# ---------------------------------------------------------------------------
# Wick ratio
# ---------------------------------------------------------------------------

class TestWickRatio:
    def test_long_wick_vs_body(self):
        # big lower wick, small body
        c = _make_candle(o=100, h=101, l=90, c=101)
        ratio = candle_wick_ratio(c, "LONG", "wick_vs_body")
        # lower_wick = 100 - 90 = 10, body = 1 → ratio = 10
        assert abs(ratio - 10.0) < 1e-9

    def test_short_wick_vs_range(self):
        c = _make_candle(o=100, h=110, l=99, c=99)
        ratio = candle_wick_ratio(c, "SHORT", "wick_vs_range")
        # upper_wick = 110 - 100 = 10, range = 11 → ≈ 0.909
        assert abs(ratio - 10 / 11) < 1e-9


# ---------------------------------------------------------------------------
# Close position check
# ---------------------------------------------------------------------------

class TestClosePosition:
    def test_long_close_upper(self):
        c = _make_candle(o=100, h=110, l=90, c=108)
        assert close_position_check(c, "LONG", 0.5) is True

    def test_long_close_lower(self):
        c = _make_candle(o=100, h=110, l=90, c=92)
        assert close_position_check(c, "LONG", 0.5) is False

    def test_short_close_lower(self):
        c = _make_candle(o=100, h=110, l=90, c=92)
        assert close_position_check(c, "SHORT", 0.5) is True

    def test_short_close_upper(self):
        c = _make_candle(o=100, h=110, l=90, c=108)
        assert close_position_check(c, "SHORT", 0.5) is False
