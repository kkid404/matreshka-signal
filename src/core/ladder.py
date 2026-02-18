from __future__ import annotations

from typing import List

from core.models import LadderStep


def normalize_ladder_steps(steps: List[LadderStep]) -> List[LadderStep]:
    """Return validated+sorted ladder steps.

    Rules:
    - tp_rr must be > 0
    - close_pct must be in (0, 1]
    - cumulative close_pct must not exceed 1.0
    - steps are sorted by tp_rr ascending
    """
    valid = [s for s in steps if s.tp_rr > 0 and 0 < s.close_pct <= 1]
    valid.sort(key=lambda s: s.tp_rr)

    total_close = 0.0
    normalized: List[LadderStep] = []
    for step in valid:
        if total_close >= 1.0:
            break
        remaining = 1.0 - total_close
        close_pct = min(step.close_pct, remaining)
        normalized.append(
            LadderStep(
                tp_rr=step.tp_rr,
                close_pct=close_pct,
                move_sl_to_be=step.move_sl_to_be,
            )
        )
        total_close += close_pct

    return normalized


def resolve_rr_target(base_rr_target: float, ladder_steps: List[LadderStep]) -> float:
    """Return effective RR target.

    If ladder is configured, RR is aligned to the farthest ladder target.
    """
    if ladder_steps:
        return max(step.tp_rr for step in ladder_steps)
    return base_rr_target
