"""Unit tests for the probability (backtest) module."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from datetime import datetime, timezone, timedelta
from models import Candle, Direction
from probability import _resolve_trade


def _ts(hour=0):
    return datetime(2024, 1, 1, hour, tzinfo=timezone.utc)


def _candle(o, h, l, c, hour=0):
    return Candle(timestamp=_ts(hour), open=o, high=h, low=l, close=c, volume=100)


class TestResolveTrade:
    def test_long_win(self):
        # entry=100, sl=95, tp=115. Future candle hits tp.
        future = [_candle(100, 120, 99, 118)]
        result = _resolve_trade(future, 0, Direction.LONG, 100, 95, 115, 10)
        assert result == "win"

    def test_long_loss(self):
        future = [_candle(100, 101, 90, 91)]
        result = _resolve_trade(future, 0, Direction.LONG, 100, 95, 115, 10)
        assert result == "loss"

    def test_short_win(self):
        # entry=100, sl=105, tp=85. Future drops to 80.
        future = [_candle(100, 101, 80, 82)]
        result = _resolve_trade(future, 0, Direction.SHORT, 100, 105, 85, 10)
        assert result == "win"

    def test_short_loss(self):
        future = [_candle(100, 110, 99, 108)]
        result = _resolve_trade(future, 0, Direction.SHORT, 100, 105, 85, 10)
        assert result == "loss"

    def test_unresolved(self):
        # Price stays flat, never hits TP or SL
        future = [_candle(100, 101, 99, 100, h) for h in range(5)]
        result = _resolve_trade(future, 0, Direction.LONG, 100, 90, 130, 5)
        assert result is None

    def test_max_bars_limit(self):
        # TP is hit but only on bar 6, max_bars=3
        flat = [_candle(100, 101, 99, 100, h) for h in range(5)]
        flat.append(_candle(100, 120, 99, 118, 5))
        result = _resolve_trade(flat, 0, Direction.LONG, 100, 90, 115, 3)
        assert result is None  # never reached within 3 bars
