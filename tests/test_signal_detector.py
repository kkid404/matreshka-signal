"""Unit tests for signal detection and trade parameter calculation."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from datetime import datetime, timezone
from core.models import Candle, Direction, LadderStep
from core.config import ScannerConfig
from core.signal_detector import (
    check_signal_candle,
    compute_trade_params,
    validate_signal,
    determine_context,
)


def _ts(day=1):
    return datetime(2024, 1, day, tzinfo=timezone.utc)


def _candle(o, h, l, c, day=1):
    return Candle(timestamp=_ts(day), open=o, high=h, low=l, close=c, volume=1000)


# ---------------------------------------------------------------------------
# Entry / SL / TP
# ---------------------------------------------------------------------------

class TestTradeParams:
    def test_long_params(self):
        cfg = ScannerConfig()
        cfg.stop_loss.buffer_mode = "percent"
        cfg.stop_loss.buffer_value = 0.1
        cfg.take_profit.rr_target = 3.0

        signal = _candle(o=100, h=102, l=90, c=101)
        entry, sl, tp, _, rr_target = compute_trade_params(
            signal, Direction.LONG, level=95.0, atr_value=5.0, cfg=cfg,
        )
        # entry = close = 101
        assert entry == 101.0
        # buffer = entry * 0.1/100 = 101 * 0.001 = 0.101
        # sl = low - buffer = 90 - 0.101 = 89.899
        assert abs(sl - (90 - 101 * 0.001)) < 0.01
        # risk = 101 - 89.91 ≈ 11.09, tp = 101 + 3*11.09 ≈ 134.27
        risk = entry - sl
        assert abs(tp - (entry + 3.0 * risk)) < 0.01
        assert rr_target == 3.0

    def test_short_params(self):
        cfg = ScannerConfig()
        cfg.stop_loss.buffer_mode = "percent"
        cfg.stop_loss.buffer_value = 0.1
        cfg.take_profit.rr_target = 3.0

        signal = _candle(o=100, h=110, l=99, c=99)
        entry, sl, tp, _, rr_target = compute_trade_params(
            signal, Direction.SHORT, level=105.0, atr_value=5.0, cfg=cfg,
        )
        assert entry == 99.0
        # buffer = entry * 0.1/100 = 99 * 0.001 = 0.099
        # sl = high + buffer = 110 + 0.099 = 110.099
        assert abs(sl - (110 + 99 * 0.001)) < 0.01
        risk = sl - entry
        assert abs(tp - (entry - 3.0 * risk)) < 0.01
        assert rr_target == 3.0

    def test_ladder_steps_are_normalized_and_rr_target_comes_from_last_step(self):
        cfg = ScannerConfig()
        cfg.stop_loss.buffer_mode = "fixed"
        cfg.stop_loss.buffer_value = 1.0
        cfg.take_profit.rr_target = 2.0
        cfg.take_profit.ladder_enabled = True
        # Includes invalid step and sum > 100% to test normalization.
        cfg.take_profit.ladder_steps = [
            LadderStep(tp_rr=2.5, close_pct=0.5, move_sl_to_be=False),
            LadderStep(tp_rr=1.0, close_pct=0.6, move_sl_to_be=True),
            LadderStep(tp_rr=-1.0, close_pct=0.3, move_sl_to_be=False),
        ]

        signal = _candle(o=100, h=104, l=95, c=100)
        entry, sl, tp, ladder, rr_target = compute_trade_params(
            signal, Direction.LONG, level=95.0, atr_value=0.0, cfg=cfg,
        )

        assert rr_target == 2.5
        assert len(ladder) == 2
        assert ladder[0].tp_rr == 1.0
        assert ladder[0].move_sl_to_be is True
        # 60% from first step + capped 40% from second step.
        assert abs(ladder[0].close_pct - 0.6) < 1e-9
        assert abs(ladder[1].close_pct - 0.4) < 1e-9

        risk = entry - sl
        assert abs(tp - (entry + rr_target * risk)) < 1e-9


# ---------------------------------------------------------------------------
# Trigger check
# ---------------------------------------------------------------------------

class TestTriggerCheck:
    def test_valid_long_trigger(self):
        cfg = ScannerConfig()
        cfg.trigger.min_wick_ratio = 1.5
        cfg.trigger.wick_measure_mode = "wick_vs_body"
        cfg.trigger.close_position_k = 0.5
        cfg.trigger.min_body_size = 0.01
        # lower_wick = 10, body = 1 → ratio 10 (> 1.5 ✓)
        # close = 101, low=90, range=12, low+0.5*12=96 → 101>=96 ✓
        c = _candle(o=100, h=102, l=90, c=101)
        assert check_signal_candle(c, Direction.LONG, cfg) is True

    def test_invalid_long_doji(self):
        cfg = ScannerConfig()
        cfg.trigger.min_body_size = 1.0
        c = _candle(o=100, h=102, l=90, c=100)  # body = 0
        assert check_signal_candle(c, Direction.LONG, cfg) is False


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidation:
    def test_sl_too_close(self):
        cfg = ScannerConfig()
        cfg.validation.min_sl_distance_pct = 0.05
        # sl_dist = 0.01% → fail
        assert validate_signal(10000, 9999, 10030, cfg) is False

    def test_sl_ok(self):
        cfg = ScannerConfig()
        cfg.validation.min_sl_distance_pct = 0.05
        cfg.validation.max_sl_distance_pct = 10.0
        assert validate_signal(100, 95, 115, cfg) is True

    def test_tp_too_far_is_rejected(self):
        cfg = ScannerConfig()
        cfg.validation.max_tp_distance_pct = 10.0
        # TP distance = 20% -> reject
        assert validate_signal(100, 95, 120, cfg) is False

    def test_sl_atr_filter_rejects_too_tight_stop(self):
        cfg = ScannerConfig()
        cfg.validation.min_sl_atr_multiple = 1.0
        # SL distance = 1, ATR = 2 => 0.5 ATR (too tight)
        assert validate_signal(100, 99, 105, cfg, atr_value=2.0) is False


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------

class TestContext:
    def test_long_context(self):
        cfg = ScannerConfig()
        cfg.context.ema_period = 3
        candles = [_candle(10, 11, 9, 10 + i, day=i + 1) for i in range(10)]
        direction = determine_context(candles, cfg)
        # Prices are rising → last close > EMA → LONG
        assert direction == Direction.LONG

    def test_short_context(self):
        cfg = ScannerConfig()
        cfg.context.ema_period = 3
        candles = [_candle(100, 101, 99, 100 - i * 5, day=i + 1) for i in range(10)]
        direction = determine_context(candles, cfg)
        assert direction == Direction.SHORT
