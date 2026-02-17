from __future__ import annotations

import logging
from typing import List

from core.config import ScannerConfig
from strategies import ALL_STRATEGIES
from strategies.base import BaseStrategy

logger = logging.getLogger("matryoshka")


def build_enabled_strategies(cfg: ScannerConfig) -> List[BaseStrategy]:
    """Instantiate enabled strategies from config."""
    strats: List[BaseStrategy] = []
    for name in cfg.enabled_strategies:
        cls = ALL_STRATEGIES.get(name)
        if cls is None:
            logger.warning("Unknown strategy '%s', skipping", name)
            continue
        strats.append(cls())
    logger.info("Active strategies: %s", [s.name for s in strats])
    return strats
