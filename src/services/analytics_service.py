from __future__ import annotations

import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict

from dotenv import load_dotenv

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
logger = logging.getLogger("analytics-service")


class AnalyticsState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.total_signals = 0
        self.by_strategy: Dict[str, int] = {}
        self.by_symbol: Dict[str, int] = {}

    def register_signal(self, symbol: str, strategy: str) -> None:
        with self.lock:
            self.total_signals += 1
            self.by_strategy[strategy] = self.by_strategy.get(strategy, 0) + 1
            self.by_symbol[symbol] = self.by_symbol.get(symbol, 0) + 1

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "total_signals": self.total_signals,
                "by_strategy": dict(self.by_strategy),
                "by_symbol": dict(self.by_symbol),
            }


class AnalyticsHandler(BaseHTTPRequestHandler):
    state: AnalyticsState = None

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json_response(200, {"ok": True, "service": "analytics"})
            return

        if self.path == "/stats":
            self._json_response(200, {"ok": True, "stats": self.state.snapshot()})
            return

        self._json_response(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/events/signal-created":
            self._json_response(404, {"ok": False, "error": "not found"})
            return

        try:
            payload = self._read_json_body()
        except ValueError:
            self._json_response(400, {"ok": False, "error": "invalid json body"})
            return

        card = payload.get("card") if isinstance(payload, dict) else None
        if not isinstance(card, dict):
            self._json_response(400, {"ok": False, "error": "card is required"})
            return

        symbol = str(card.get("symbol", ""))
        strategy = str(card.get("strategy_name", "unknown"))
        if not symbol:
            self._json_response(400, {"ok": False, "error": "card.symbol is required"})
            return

        self.state.register_signal(symbol=symbol, strategy=strategy)
        self._json_response(200, {"ok": True})

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

    AnalyticsHandler.state = AnalyticsState()

    host = os.getenv("ANALYTICS_SERVICE_HOST", "0.0.0.0")
    port = int(os.getenv("ANALYTICS_SERVICE_PORT", "8084"))

    server = ThreadingHTTPServer((host, port), AnalyticsHandler)
    logger.info("analytics-service listening on %s:%d", host, port)
    server.serve_forever()


if __name__ == "__main__":
    main()
