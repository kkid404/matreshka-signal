"""Base strategy interface."""

from __future__ import annotations

import abc
import logging
from typing import List, Optional

from core.config import ScannerConfig
from core.models import Candle, SignalCard

logger = logging.getLogger(__name__)


class BaseStrategy(abc.ABC):
    """Every strategy must implement `scan`."""

    name: str = "base"

    @abc.abstractmethod
    def scan(
        self,
        symbol: str,
        d1_candles: List[Candle],
        h4_candles: List[Candle],
        cfg: ScannerConfig,
    ) -> Optional[SignalCard]:
        """Return a SignalCard if a signal is found, else None."""

    @staticmethod
    def _tv_link(symbol: str) -> str:
        base = symbol.replace("USDT", "")
        return f"https://www.tradingview.com/chart/?symbol=BYBIT:{base}USDT.P"
