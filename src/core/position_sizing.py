"""Position sizing engine for risk-based trade allocation."""

from __future__ import annotations

from dataclasses import dataclass
import math

from core.risk_profile import RiskProfile


@dataclass
class PositionSizingResult:
    ok: bool
    reason: str = ""
    risk_amount_usdt: float = 0.0
    stop_distance: float = 0.0
    raw_size: float = 0.0
    recommended_size: float = 0.0
    estimated_loss_at_sl: float = 0.0
    notional_usdt: float = 0.0


def calculate_position_size(
    *,
    entry_price: float,
    stop_loss_price: float,
    budget_usdt: float,
    risk_per_trade_pct: float,
    qty_step: float = 0.0,
    min_qty: float = 0.0,
    min_notional: float = 0.0,
) -> PositionSizingResult:
    if not math.isfinite(entry_price):
        return PositionSizingResult(ok=False, reason="entry_price must be a finite number")
    if not math.isfinite(stop_loss_price):
        return PositionSizingResult(ok=False, reason="stop_loss_price must be a finite number")
    if not math.isfinite(budget_usdt):
        return PositionSizingResult(ok=False, reason="budget_usdt must be a finite number")
    if not math.isfinite(risk_per_trade_pct):
        return PositionSizingResult(ok=False, reason="risk_per_trade_pct must be a finite number")
    if not math.isfinite(qty_step):
        return PositionSizingResult(ok=False, reason="qty_step must be a finite number")
    if not math.isfinite(min_qty):
        return PositionSizingResult(ok=False, reason="min_qty must be a finite number")
    if not math.isfinite(min_notional):
        return PositionSizingResult(ok=False, reason="min_notional must be a finite number")

    if entry_price <= 0:
        return PositionSizingResult(ok=False, reason="entry_price must be > 0")
    if budget_usdt <= 0:
        return PositionSizingResult(ok=False, reason="budget_usdt must be > 0")
    if risk_per_trade_pct <= 0:
        return PositionSizingResult(ok=False, reason="risk_per_trade_pct must be > 0")
    if qty_step < 0:
        return PositionSizingResult(ok=False, reason="qty_step must be >= 0")
    if min_qty < 0:
        return PositionSizingResult(ok=False, reason="min_qty must be >= 0")
    if min_notional < 0:
        return PositionSizingResult(ok=False, reason="min_notional must be >= 0")

    stop_distance = abs(entry_price - stop_loss_price)
    if stop_distance <= 0:
        return PositionSizingResult(ok=False, reason="stop_distance must be > 0")

    risk_amount = budget_usdt * (risk_per_trade_pct / 100.0)
    raw_size = risk_amount / stop_distance
    if raw_size <= 0:
        return PositionSizingResult(ok=False, reason="raw_size must be > 0")

    size = _round_down_to_step(raw_size, qty_step)
    if size <= 0:
        return PositionSizingResult(
            ok=False,
            reason="recommended_size is 0 after step rounding",
            risk_amount_usdt=risk_amount,
            stop_distance=stop_distance,
            raw_size=raw_size,
        )

    if min_qty > 0 and size < min_qty:
        return PositionSizingResult(
            ok=False,
            reason="recommended_size is below min_qty",
            risk_amount_usdt=risk_amount,
            stop_distance=stop_distance,
            raw_size=raw_size,
            recommended_size=size,
        )

    notional = size * entry_price
    if min_notional > 0 and notional < min_notional:
        return PositionSizingResult(
            ok=False,
            reason="recommended_size is below min_notional",
            risk_amount_usdt=risk_amount,
            stop_distance=stop_distance,
            raw_size=raw_size,
            recommended_size=size,
            notional_usdt=notional,
        )

    estimated_loss = size * stop_distance
    return PositionSizingResult(
        ok=True,
        risk_amount_usdt=risk_amount,
        stop_distance=stop_distance,
        raw_size=raw_size,
        recommended_size=size,
        estimated_loss_at_sl=estimated_loss,
        notional_usdt=notional,
    )


def calculate_position_size_for_profile(
    *,
    profile: RiskProfile,
    entry_price: float,
    stop_loss_price: float,
    qty_step: float = 0.0,
    min_qty: float = 0.0,
    min_notional: float = 0.0,
) -> PositionSizingResult:
    return calculate_position_size(
        entry_price=entry_price,
        stop_loss_price=stop_loss_price,
        budget_usdt=profile.budget_usdt,
        risk_per_trade_pct=profile.risk_per_trade_pct,
        qty_step=qty_step,
        min_qty=min_qty,
        min_notional=min_notional,
    )


def _round_down_to_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    units = math.floor((value / step) + 1e-12)
    rounded = units * step
    return round(rounded, 12)
