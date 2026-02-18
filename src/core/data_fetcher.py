"""Bybit OHLCV data fetcher via ccxt."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import List, Optional

import ccxt

from core.models import Candle

logger = logging.getLogger(__name__)

_RATE_LIMIT_SLEEP = 0.25


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

    def get_all_usdt_perpetuals(
        self,
        min_volume_24h: float = 0.0,
        min_open_interest: float = 0.0,
        exclude: Optional[List[str]] = None,
    ) -> List[str]:
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
            oi_value = self._extract_open_interest_value(t)
            if oi_value < min_open_interest:
                continue
            perps.append((bybit_sym, vol))
        perps.sort(key=lambda x: x[1], reverse=True)
        logger.info(
            "Found %d USDT perpetual pairs (min_vol=%.0f, min_oi=%.0f)",
            len(perps),
            min_volume_24h,
            min_open_interest,
        )
        return [s for s, _ in perps]

    def get_top_usdt_perpetuals(
        self,
        top_n: int = 50,
        min_volume_24h: float = 0.0,
        min_open_interest: float = 0.0,
        exclude: Optional[List[str]] = None,
    ) -> List[str]:
        all_syms = self.get_all_usdt_perpetuals(min_volume_24h, min_open_interest, exclude)
        return all_syms[:top_n]

    @staticmethod
    def _extract_open_interest_value(ticker: dict) -> float:
        candidates = [
            ticker.get("openInterestValue"),
            ticker.get("openInterest"),
        ]

        info = ticker.get("info") or {}
        if isinstance(info, dict):
            candidates.extend(
                [
                    info.get("openInterestValue"),
                    info.get("openInterest"),
                    info.get("open_interest"),
                ]
            )

        for value in candidates:
            try:
                if value is None or value == "":
                    continue
                parsed = float(value)
                if parsed > 0:
                    return parsed
            except (TypeError, ValueError):
                continue
        return 0.0

    def fetch_candles(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 200,
        since_ms: Optional[int] = None,
    ) -> List[Candle]:
        ccxt_symbol = self._to_ccxt_symbol(symbol)
        tf = self._normalize_timeframe(timeframe)
        all_candles: List[Candle] = []
        remaining = limit
        since = since_ms

        if since is None:
            tf_ms = self._timeframe_to_ms(tf)
            now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
            since = max(0, now_ms - tf_ms * max(limit, 1))

        while remaining > 0:
            batch_size = min(remaining, 200)
            retries = 3
            raw = None
            prev_since = since
            for attempt in range(retries):
                try:
                    raw = self.exchange.fetch_ohlcv(ccxt_symbol, tf, since=since, limit=batch_size)
                    break
                except (ccxt.NetworkError, ccxt.ExchangeNotAvailable) as exc:
                    logger.warning("Retry %d/%d for %s: %s", attempt + 1, retries, symbol, exc)
                    time.sleep(2 ** attempt)
            if raw is None:
                logger.error("Failed to fetch candles for %s after %d retries", symbol, retries)
                break
            if not raw:
                break

            raw_sorted = sorted(raw, key=lambda x: x[0])

            for r in raw_sorted:
                all_candles.append(Candle(
                    timestamp=datetime.fromtimestamp(r[0] / 1000, tz=timezone.utc),
                    open=float(r[1]),
                    high=float(r[2]),
                    low=float(r[3]),
                    close=float(r[4]),
                    volume=float(r[5]),
                ))
            since = raw_sorted[-1][0] + 1
            remaining -= len(raw_sorted)

            if prev_since is not None and since <= prev_since:
                break
            time.sleep(_RATE_LIMIT_SLEEP)

        all_candles.sort(key=lambda c: c.timestamp)

        dedup: List[Candle] = []
        seen_ts = set()
        for c in all_candles:
            if c.timestamp in seen_ts:
                continue
            seen_ts.add(c.timestamp)
            dedup.append(c)

        return dedup

    def _to_ccxt_symbol(self, symbol: str) -> str:
        for mkt_sym, mkt in self.exchange.markets.items():
            if mkt.get("id") == symbol and mkt.get("linear"):
                return mkt_sym
        if symbol.endswith("USDT"):
            base = symbol[:-4]
            return f"{base}/USDT:USDT"
        return symbol

    @staticmethod
    def _from_ccxt_symbol(ccxt_symbol: str) -> str:
        return ccxt_symbol.split("/")[0] + "USDT"

    @staticmethod
    def _timeframe_to_ms(timeframe: str) -> int:
        tf = timeframe.strip()
        unit = tf[-1]
        value = int(tf[:-1])
        mult = {
            "m": 60_000,
            "h": 3_600_000,
            "d": 86_400_000,
            "w": 604_800_000,
            "M": 2_592_000_000,
            "D": 86_400_000,
            "H": 3_600_000,
        }.get(unit)
        if mult is None:
            raise ValueError(f"Unsupported timeframe: {timeframe}")
        return value * mult

    @staticmethod
    def _normalize_timeframe(timeframe: str) -> str:
        tf = timeframe.strip()
        if len(tf) < 2:
            return tf
        unit = tf[-1]
        value = tf[:-1]
        if unit in ("H", "h"):
            return f"{value}h"
        if unit in ("D", "d"):
            return f"{value}d"
        if unit in ("W", "w"):
            return f"{value}w"
        if unit == "m":
            return f"{value}m"
        if unit == "M":
            return f"{value}M"
        return tf
