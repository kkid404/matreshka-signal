from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Dict, List, Optional

from core.models import Candle

logger = logging.getLogger(__name__)


class MarketDataClient:
    """HTTP client for market-data-service."""

    def __init__(self, base_url: str, timeout: int = 60):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get_all_usdt_perpetuals(
        self,
        min_volume_24h: float = 0.0,
        exclude: Optional[List[str]] = None,
    ) -> List[str]:
        payload = {
            "mode": "all",
            "top_n": 0,
            "min_volume_24h": min_volume_24h,
            "exclude": exclude or [],
            "symbols": [],
        }
        body = self._post_json("/symbols/resolve", payload)
        if not body.get("ok"):
            return []
        return [str(s) for s in body.get("symbols", [])]

    def get_top_usdt_perpetuals(
        self,
        top_n: int = 50,
        min_volume_24h: float = 0.0,
        exclude: Optional[List[str]] = None,
    ) -> List[str]:
        payload = {
            "mode": "top_n",
            "top_n": top_n,
            "min_volume_24h": min_volume_24h,
            "exclude": exclude or [],
            "symbols": [],
        }
        body = self._post_json("/symbols/resolve", payload)
        if not body.get("ok"):
            return []
        return [str(s) for s in body.get("symbols", [])]

    def fetch_candles(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 200,
        since_ms: Optional[int] = None,
    ) -> List[Candle]:
        payload: Dict[str, object] = {
            "symbol": symbol,
            "timeframe": timeframe,
            "limit": limit,
        }
        if since_ms is not None:
            payload["since_ms"] = since_ms

        body = self._post_json("/candles", payload)
        if not body.get("ok"):
            return []

        raw = body.get("candles", []) or []
        candles: List[Candle] = []
        for item in raw:
            ts = str(item.get("timestamp", ""))
            if ts.endswith("Z"):
                ts = ts[:-1] + "+00:00"
            candles.append(
                Candle(
                    timestamp=datetime.fromisoformat(ts),
                    open=float(item.get("open", 0.0)),
                    high=float(item.get("high", 0.0)),
                    low=float(item.get("low", 0.0)),
                    close=float(item.get("close", 0.0)),
                    volume=float(item.get("volume", 0.0)),
                )
            )
        return candles

    def _post_json(self, path: str, payload: dict) -> dict:
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            logger.error("market-data-service error on %s: %s", path, exc)
            return {"ok": False}
