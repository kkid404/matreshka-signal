"""Unit tests for risk-based position sizing engine."""

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.position_sizing import calculate_position_size, calculate_position_size_for_profile
from core.risk_profile import RiskProfile


def test_calculate_position_size_base_formula():
    result = calculate_position_size(
        entry_price=100.0,
        stop_loss_price=95.0,
        budget_usdt=1000.0,
        risk_per_trade_pct=1.0,
    )

    assert result.ok is True
    assert result.risk_amount_usdt == 10.0
    assert result.stop_distance == 5.0
    assert result.raw_size == 2.0
    assert result.recommended_size == 2.0
    assert result.estimated_loss_at_sl == 10.0


def test_calculate_position_size_rounds_down_by_qty_step():
    result = calculate_position_size(
        entry_price=100.0,
        stop_loss_price=97.0,
        budget_usdt=1000.0,
        risk_per_trade_pct=1.0,
        qty_step=0.4,
    )

    # raw_size = 10 / 3 = 3.3333..., rounded down to step 0.4 => 3.2
    assert result.ok is True
    assert abs(result.raw_size - (10.0 / 3.0)) < 1e-9
    assert result.recommended_size == 3.2
    assert result.estimated_loss_at_sl <= result.risk_amount_usdt


def test_calculate_position_size_rejects_zero_stop_distance():
    result = calculate_position_size(
        entry_price=100.0,
        stop_loss_price=100.0,
        budget_usdt=1000.0,
        risk_per_trade_pct=1.0,
    )

    assert result.ok is False
    assert "stop_distance" in result.reason


def test_calculate_position_size_rejects_below_min_qty():
    result = calculate_position_size(
        entry_price=100.0,
        stop_loss_price=90.0,
        budget_usdt=1000.0,
        risk_per_trade_pct=1.0,
        min_qty=2.0,
    )

    # risk_amount=10, stop_distance=10 => size=1.0 < min_qty
    assert result.ok is False
    assert "min_qty" in result.reason


def test_calculate_position_size_rejects_below_min_notional():
    result = calculate_position_size(
        entry_price=100.0,
        stop_loss_price=90.0,
        budget_usdt=1000.0,
        risk_per_trade_pct=1.0,
        min_notional=200.0,
    )

    # size=1.0, notional=100 < 200
    assert result.ok is False
    assert "min_notional" in result.reason


def test_calculate_position_size_for_profile_uses_profile_values():
    profile = RiskProfile(user_id=77, budget_usdt=2500.0, risk_per_trade_pct=2.0)
    result = calculate_position_size_for_profile(
        profile=profile,
        entry_price=50.0,
        stop_loss_price=49.0,
    )

    # risk_amount = 50, stop_distance = 1 => size = 50
    assert result.ok is True
    assert result.risk_amount_usdt == 50.0
    assert result.recommended_size == 50.0


def test_calculate_position_size_rejects_non_finite_inputs():
    result = calculate_position_size(
        entry_price=math.nan,
        stop_loss_price=95.0,
        budget_usdt=1000.0,
        risk_per_trade_pct=1.0,
    )
    assert result.ok is False
    assert "finite" in result.reason


def test_calculate_position_size_rejects_negative_limits():
    result = calculate_position_size(
        entry_price=100.0,
        stop_loss_price=95.0,
        budget_usdt=1000.0,
        risk_per_trade_pct=1.0,
        qty_step=-0.1,
    )
    assert result.ok is False
    assert "qty_step" in result.reason
