"""Strategy registry for the Matryoshka scanner."""

from strategies.base import BaseStrategy
from strategies.matryoshka import MatryoshkaStrategy
from strategies.ema_bounce import EMABounceStrategy
from strategies.breakout import BreakoutStrategy
from strategies.engulfing import EngulfingStrategy
from strategies.momentum_break import MomentumBreakStrategy
from strategies.ema_cross import EMACrossStrategy

ALL_STRATEGIES: dict[str, type[BaseStrategy]] = {
    "matryoshka": MatryoshkaStrategy,
    "ema_bounce": EMABounceStrategy,
    "breakout": BreakoutStrategy,
    "engulfing": EngulfingStrategy,
    "momentum_break": MomentumBreakStrategy,
    "ema_cross": EMACrossStrategy,
}
