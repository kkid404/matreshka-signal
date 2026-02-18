"""Tests for auto-levels pipeline: swings -> clusters -> nearest levels."""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.config import ScannerConfig
from core.levels import detect_swing_highs_lows, resolve_levels, select_nearest_levels
from core.models import Candle


def _candles_from_close(closes):
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    candles = []
    for i, c in enumerate(closes):
        candles.append(
            Candle(
                timestamp=start + timedelta(hours=4 * i),
                open=c - 0.8,
                high=c + 1.2,
                low=c - 1.4,
                close=c,
                volume=1000.0,
            )
        )
    return candles


def test_select_nearest_levels_returns_sorted_slice_near_reference():
    levels = [80.0, 92.0, 96.0, 103.0, 120.0]
    nearest = select_nearest_levels(levels, reference_price=100.0, nearest_count=3)
    assert nearest == [92.0, 96.0, 103.0]


def test_resolve_levels_manual_mode_returns_manual_levels_only():
    cfg = ScannerConfig()
    cfg.levels_mode = "manual"
    cfg.levels_manual = {"BTCUSDT": [43000.0, 42000.0, 44000.0]}

    candles = _candles_from_close([43000.0, 43100.0, 42900.0])
    levels = resolve_levels(cfg.levels_manual, "BTCUSDT", candles, cfg, reference_price=43000.0)

    assert levels == [42000.0, 43000.0, 44000.0]


def test_resolve_levels_auto_mode_builds_and_limits_nearest_levels_on_synthetic_data():
    cfg = ScannerConfig()
    cfg.levels_mode = "auto"
    cfg.auto_levels.swing_order = 2
    cfg.auto_levels.cluster_tolerance_pct = 0.8
    cfg.auto_levels.nearest_count = 3

    # Synthetic wave with clear local peaks/troughs.
    closes = [100, 103, 108, 104, 99, 95, 98, 104, 111, 107, 102, 96, 99, 105, 112, 108, 101]
    candles = _candles_from_close(closes)

    raw = detect_swing_highs_lows(candles, order=cfg.auto_levels.swing_order)
    assert raw, "expected swing levels on synthetic wave"

    levels = resolve_levels(cfg.levels_manual, "BTCUSDT", candles, cfg, reference_price=103.0)

    assert 1 <= len(levels) <= 3
    # Returned levels are nearest to reference; ensure they are centered around recent price zone.
    assert all(90.0 <= lv <= 115.0 for lv in levels)


def test_resolve_levels_auto_mode_on_realistic_price_shape():
    cfg = ScannerConfig()
    cfg.levels_mode = "auto"
    cfg.auto_levels.swing_order = 3
    cfg.auto_levels.cluster_tolerance_pct = 0.6
    cfg.auto_levels.nearest_count = 4

    # BTC-like profile: trend up, pullback, continuation, with noise.
    closes = [
        42000, 42200, 42550, 42900, 43200, 42800, 42450, 42100,
        42300, 42700, 43150, 43600, 43900, 43500, 43100, 42850,
        43000, 43400, 43850, 44200, 44500, 44100, 43700, 43350,
        43600, 44000, 44450, 44800,
    ]
    candles = _candles_from_close(closes)

    levels = resolve_levels(cfg.levels_manual, "BTCUSDT", candles, cfg, reference_price=43950.0)

    assert 1 <= len(levels) <= 4
    # Auto-levels should stay in realistic neighborhood of this dataset.
    assert all(41000.0 <= lv <= 45500.0 for lv in levels)
