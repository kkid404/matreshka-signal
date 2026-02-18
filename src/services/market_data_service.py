from __future__ import annotations

import json
import logging
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

from core.data_fetcher import DataFetcher

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
logger = logging.getLogger("market-data-service")


class MarketDataState:
    def __init__(self, fetcher: DataFetcher, cache_ttl_seconds: int, min_interval_ms: int):
        self.fetcher = fetcher
        self.cache_ttl_seconds = cache_ttl_seconds
        self.min_interval_ms = min_interval_ms
        self.cache: Dict[str, Tuple[float, Any]] = {}
        self.cache_lock = threading.Lock()
        self.rate_lock = threading.Lock()
        self.last_request_at = 0.0

    def throttle(self) -> None:
        with self.rate_lock:
            now = time.time()
            min_interval = self.min_interval_ms / 1000.0
            elapsed = now - self.last_request_at
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
            self.last_request_at = time.time()

    def get_cached(self, key: str) -> Optional[Any]:
        with self.cache_lock:
            item = self.cache.get(key)
            if not item:
                return None
            expires_at, data = item
            if time.time() >= expires_at:
                self.cache.pop(key, None)
                return None
            return data

    def set_cached(self, key: str, data: Any) -> None:
        with self.cache_lock:
            self.cache[key] = (time.time() + self.cache_ttl_seconds, data)


class MarketDataHandler(BaseHTTPRequestHandler):
    state: MarketDataState = None

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json_response(200, {"ok": True, "service": "market-data"})
            return
        self._json_response(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        try:
            payload = self._read_json_body()
        except ValueError:
            self._json_response(400, {"ok": False, "error": "invalid json body"})
            return

        if self.path == "/candles":
            self._handle_candles(payload)
            return

        if self.path == "/symbols/resolve":
            self._handle_symbols(payload)
            return

        self._json_response(404, {"ok": False, "error": "not found"})

    def _handle_candles(self, payload: dict) -> None:
        symbol = str(payload.get("symbol", "")).strip().upper()
        timeframe = str(payload.get("timeframe", "")).strip()
        limit = int(payload.get("limit", 200) or 200)
        since_ms = payload.get("since_ms")

        if not symbol or not timeframe:
            self._json_response(400, {"ok": False, "error": "symbol and timeframe are required"})
            return

        cache_key = f"candles:{symbol}:{timeframe}:{limit}:{since_ms}"
        cached = self.state.get_cached(cache_key)
        if cached is not None:
            self._json_response(200, {"ok": True, "cached": True, "candles": cached})
            return

        self.state.throttle()
        candles = self.state.fetcher.fetch_candles(symbol, timeframe, limit=limit, since_ms=since_ms)
        data = [
            {
                "timestamp": c.timestamp.isoformat(),
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
            }
            for c in candles
        ]
        self.state.set_cached(cache_key, data)
        self._json_response(200, {"ok": True, "cached": False, "candles": data})

    def _handle_symbols(self, payload: dict) -> None:
        mode = str(payload.get("mode", "all"))
        top_n = int(payload.get("top_n", 100) or 100)
        min_volume_24h = float(payload.get("min_volume_24h", 0.0) or 0.0)
        min_open_interest = float(payload.get("min_open_interest", 0.0) or 0.0)
        exclude = payload.get("exclude") or []
        symbols = payload.get("symbols") or []

        cache_key = (
            f"symbols:{mode}:{top_n}:{min_volume_24h}:{min_open_interest}:"
            f"{','.join(sorted(exclude))}:{','.join(symbols)}"
        )
        cached = self.state.get_cached(cache_key)
        if cached is not None:
            self._json_response(200, {"ok": True, "cached": True, "symbols": cached})
            return

        self.state.throttle()
        if mode == "manual":
            resolved = [str(s).upper() for s in symbols]
        elif mode == "top_n":
            resolved = self.state.fetcher.get_top_usdt_perpetuals(
                top_n=top_n,
                min_volume_24h=min_volume_24h,
                min_open_interest=min_open_interest,
                exclude=list(exclude),
            )
        else:
            resolved = self.state.fetcher.get_all_usdt_perpetuals(
                min_volume_24h=min_volume_24h,
                min_open_interest=min_open_interest,
                exclude=list(exclude),
            )

        self.state.set_cached(cache_key, resolved)
        self._json_response(200, {"ok": True, "cached": False, "symbols": resolved})

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b"{}"
        body = json.loads(raw.decode("utf-8"))
        if not isinstance(body, dict):
            raise ValueError("body must be object")
        return body

    def _json_response(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        logger.debug("http: " + format, *args)


def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

    ttl = int(os.getenv("MARKET_DATA_CACHE_TTL_SECONDS", "120"))
    min_interval_ms = int(os.getenv("MARKET_DATA_MIN_REQUEST_INTERVAL_MS", "200"))

    fetcher = DataFetcher()
    state = MarketDataState(fetcher=fetcher, cache_ttl_seconds=ttl, min_interval_ms=min_interval_ms)
    MarketDataHandler.state = state

    host = os.getenv("MARKET_DATA_SERVICE_HOST", "0.0.0.0")
    port = int(os.getenv("MARKET_DATA_SERVICE_PORT", "8083"))

    server = ThreadingHTTPServer((host, port), MarketDataHandler)
    logger.info("market-data-service listening on %s:%d", host, port)
    server.serve_forever()


if __name__ == "__main__":
    main()
