"""Unit tests for scan pipeline edge-case handling."""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from application.use_cases import scan as scan_module
from application.use_cases.scan import run_scan
from core.config import ScannerConfig
from core.models import Candle, Direction, SignalCard


class FakeFetcher:
    def __init__(self, d1_by_symbol, h4_by_symbol):
        self._d1 = d1_by_symbol
        self._h4 = h4_by_symbol

    def fetch_candles(self, symbol, timeframe, limit=200):
        if timeframe == "1d":
            return self._d1.get(symbol, [])
        return self._h4.get(symbol, [])


class FakeCache:
    def is_new(self, symbol, signal_time_iso, direction):
        return True

    def mark(self, symbol, signal_time_iso, direction):
        return None


class FakeStrategy:
    name = "fake"

    def __init__(self):
        self.calls = []

    def scan(self, symbol, d1_candles, h4_candles, cfg):
        self.calls.append(symbol)
        signal_time = h4_candles[-2].timestamp
        return SignalCard(
            symbol=symbol,
            direction=Direction.LONG,
            timeframe="H4",
            signal_candle_time=signal_time,
            level_price=h4_candles[-2].close,
            entry_price=h4_candles[-2].close,
            stop_loss=h4_candles[-2].close - 5,
            take_profit=h4_candles[-2].close + 15,
            rr_target=3.0,
            probability_percent=0.0,
            sample_size_n=0,
            strategy_name=self.name,
        )


def _build_candles(count, step, start=None, volume=100.0):
    start = start or datetime(2024, 1, 1, tzinfo=timezone.utc)
    candles = []
    price = 100.0
    for i in range(count):
        ts = start + i * step
        candles.append(
            Candle(
                timestamp=ts,
                open=price,
                high=price + 2,
                low=price - 2,
                close=price + 1,
                volume=volume,
            )
        )
        price += 0.1
    return candles


def test_run_scan_skips_symbols_with_gaps_or_illiquid_data():
    cfg = ScannerConfig()
    cfg.context.timeframe = "1d"
    cfg.setup.timeframe = "4h"
    cfg.validation.min_d1_candles = 10
    cfg.validation.min_h4_candles = 20
    cfg.validation.max_candle_gap_factor = 2.0
    cfg.validation.max_zero_volume_share = 0.3

    d1 = _build_candles(20, timedelta(days=1), volume=100)

    h4_good = _build_candles(40, timedelta(hours=4), volume=100)

    h4_gap = _build_candles(40, timedelta(hours=4), volume=100)
    h4_gap[25] = Candle(
        timestamp=h4_gap[24].timestamp + timedelta(hours=20),
        open=h4_gap[25].open,
        high=h4_gap[25].high,
        low=h4_gap[25].low,
        close=h4_gap[25].close,
        volume=h4_gap[25].volume,
    )

    h4_illiquid = _build_candles(40, timedelta(hours=4), volume=0)
    for i in range(10):
        h4_illiquid[i] = Candle(
            timestamp=h4_illiquid[i].timestamp,
            open=h4_illiquid[i].open,
            high=h4_illiquid[i].high,
            low=h4_illiquid[i].low,
            close=h4_illiquid[i].close,
            volume=100,
        )

    fetcher = FakeFetcher(
        d1_by_symbol={
            "GOODUSDT": d1,
            "BADGAPUSDT": d1,
            "ILLIQUSDT": d1,
        },
        h4_by_symbol={
            "GOODUSDT": h4_good,
            "BADGAPUSDT": h4_gap,
            "ILLIQUSDT": h4_illiquid,
        },
    )

    strategy = FakeStrategy()

    original_throttle = scan_module._SYMBOL_THROTTLE
    scan_module._SYMBOL_THROTTLE = 0.0
    try:
        cards = run_scan(
            cfg=cfg,
            fetcher=fetcher,
            cache=FakeCache(),
            symbols=["GOODUSDT", "BADGAPUSDT", "ILLIQUSDT"],
            strategies=[strategy],
        )
    finally:
        scan_module._SYMBOL_THROTTLE = original_throttle

    assert [c.symbol for c in cards] == ["GOODUSDT"]
    assert strategy.calls == ["GOODUSDT"]


def test_run_scan_skips_symbol_when_d1_data_is_empty():
    cfg = ScannerConfig()
    cfg.context.timeframe = "1d"
    cfg.setup.timeframe = "4h"
    cfg.validation.min_d1_candles = 5
    cfg.validation.min_h4_candles = 5

    fetcher = FakeFetcher(
        d1_by_symbol={"NOD1USDT": []},
        h4_by_symbol={"NOD1USDT": _build_candles(10, timedelta(hours=4), volume=100)},
    )

    strategy = FakeStrategy()

    original_throttle = scan_module._SYMBOL_THROTTLE
    scan_module._SYMBOL_THROTTLE = 0.0
    try:
        cards = run_scan(
            cfg=cfg,
            fetcher=fetcher,
            cache=FakeCache(),
            symbols=["NOD1USDT"],
            strategies=[strategy],
        )
    finally:
        scan_module._SYMBOL_THROTTLE = original_throttle

    assert cards == []
    assert strategy.calls == []
