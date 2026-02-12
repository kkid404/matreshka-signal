"""Bybit OHLCV data fetcher via ccxt."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import List, Optional

import ccxt

from models import Candle

logger = logging.getLogger(__name__)

# Bybit rate-limit: we add a small sleep between paginated calls.
_RATE_LIMIT_SLEEP = 0.25  # seconds


class DataFetcher:
    """Fetches OHLCV candles from Bybit linear (USDT perpetual)."""

    def __init__(self, api_key: str = "", api_secret: str = ""):
        self.exchange = ccxt.bybit({
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
            "options": {"defaultType": "linear"},
        })
        self.exchange.load_markets()

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def get_all_usdt_perpetuals(
        self,
        min_volume_24h: float = 0.0,
        exclude: Optional[List[str]] = None,
    ) -> List[str]:
        """Return ALL USDT perpetual symbols, filtered and sorted by 24h volume."""
        exclude_set = set(exclude or [])
        tickers = self.exchange.fetch_tickers()
        perps = []
        for sym, t in tickers.items():
            if not sym.endswith("/USDT:USDT"):
                continue
            bybit_sym = self._from_ccxt_symbol(sym)
            if bybit_sym in exclude_set:
                continue
            vol = t.get("quoteVolume") or 0
            if vol < min_volume_24h:
                continue
            perps.append((bybit_sym, vol))
        perps.sort(key=lambda x: x[1], reverse=True)
        logger.info("Found %d USDT perpetual pairs (min_vol=%.0f)", len(perps), min_volume_24h)
        return [s for s, _ in perps]

    def get_top_usdt_perpetuals(
        self,
        top_n: int = 50,
        min_volume_24h: float = 0.0,
        exclude: Optional[List[str]] = None,
    ) -> List[str]:
        """Return top-N USDT perpetual symbols sorted by 24 h quote volume."""
        all_syms = self.get_all_usdt_perpetuals(min_volume_24h, exclude)
        return all_syms[:top_n]

    def fetch_candles(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 200,
        since_ms: Optional[int] = None,
    ) -> List[Candle]:
        """Fetch OHLCV candles with automatic pagination when limit > 200."""
        ccxt_symbol = self._to_ccxt_symbol(symbol)
        all_candles: List[Candle] = []
        remaining = limit
        since = since_ms

        while remaining > 0:
            batch_size = min(remaining, 200)
            retries = 3
            raw = None
            for attempt in range(retries):
                try:
                    raw = self.exchange.fetch_ohlcv(
                        ccxt_symbol, timeframe, since=since, limit=batch_size
                    )
                    break
                except (ccxt.NetworkError, ccxt.ExchangeNotAvailable) as exc:
                    logger.warning("Retry %d/%d for %s: %s", attempt + 1, retries, symbol, exc)
                    time.sleep(2 ** attempt)
            if raw is None:
                logger.error("Failed to fetch candles for %s after %d retries", symbol, retries)
                break
            if not raw:
                break

            for r in raw:
                all_candles.append(Candle(
                    timestamp=datetime.fromtimestamp(r[0] / 1000, tz=timezone.utc),
                    open=float(r[1]),
                    high=float(r[2]),
                    low=float(r[3]),
                    close=float(r[4]),
                    volume=float(r[5]),
                ))
            since = raw[-1][0] + 1  # next ms after last candle
            remaining -= len(raw)
            if len(raw) < batch_size:
                break
            time.sleep(_RATE_LIMIT_SLEEP)

        return all_candles

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _to_ccxt_symbol(self, symbol: str) -> str:
        """Convert 'BTCUSDT' → 'BTC/USDT:USDT' for linear perp."""
        # Try direct market lookup first (handles edge cases like 1000PEPEUSDT)
        for mkt_sym, mkt in self.exchange.markets.items():
            if mkt.get("id") == symbol and mkt.get("linear"):
                return mkt_sym
        # Fallback: strip trailing USDT
        if symbol.endswith("USDT"):
            base = symbol[:-4]
            return f"{base}/USDT:USDT"
        return symbol

    @staticmethod
    def _from_ccxt_symbol(ccxt_symbol: str) -> str:
        """Convert 'BTC/USDT:USDT' → 'BTCUSDT'."""
        return ccxt_symbol.split("/")[0] + "USDT"
