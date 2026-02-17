from __future__ import annotations

import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from dotenv import load_dotenv

from application.use_cases.configuration import build_scanner_config
from application.use_cases.replay import replay_symbol_history
from application.use_cases.scan import resolve_symbols, run_scan
from application.use_cases.strategy_catalog import build_enabled_strategies
from core.cache import SignalCache
from infrastructure.market_data_client import MarketDataClient
from infrastructure.signal_event_publisher import SignalEventPublisher
from strategies import ALL_STRATEGIES

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
logger = logging.getLogger("signal-engine-service")


class SignalEngineHandler(BaseHTTPRequestHandler):
    cfg = None
    fetcher = None
    strategies = None
    cache = None
    event_publisher = None

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json_response(200, {"ok": True, "service": "signal-engine"})
            return

        if self.path == "/strategies":
            enabled = [s.name for s in self.strategies]
            self._json_response(
                200,
                {
                    "ok": True,
                    "enabled": enabled,
                    "all": list(ALL_STRATEGIES.keys()),
                },
            )
            return

        self._json_response(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        if self.path == "/replay/run":
            self._handle_replay()
            return

        if self.path == "/scan/run":
            self._handle_scan()
            return

        self._json_response(404, {"ok": False, "error": "not found"})

    def _handle_replay(self) -> None:
        try:
            payload = self._read_json_body()
        except ValueError:
            self._json_response(400, {"ok": False, "error": "invalid json body"})
            return

        symbol = str(payload.get("symbol", "BTCUSDT")).upper().replace("/", "").replace(":USDT", "")
        lookback_raw = payload.get("lookback", 1200)
        try:
            lookback = int(lookback_raw)
        except (TypeError, ValueError):
            self._json_response(400, {"ok": False, "error": "lookback must be int"})
            return

        if lookback < 200 or lookback > 5000:
            self._json_response(400, {"ok": False, "error": "lookback must be in 200..5000"})
            return

        try:
            cards = replay_symbol_history(self.cfg, self.fetcher, symbol, self.strategies, lookback)
            self._json_response(
                200,
                {
                    "ok": True,
                    "symbol": symbol,
                    "count": len(cards),
                    "cards": [c.to_dict() for c in cards],
                },
            )
        except Exception as exc:
            logger.exception("replay failed")
            self._json_response(500, {"ok": False, "error": str(exc)})

    def _handle_scan(self) -> None:
        try:
            symbols = resolve_symbols(self.cfg, self.fetcher)
            cards = run_scan(self.cfg, self.fetcher, self.cache, symbols, self.strategies)
            published = 0
            if self.event_publisher is not None:
                for card in cards:
                    published += self.event_publisher.publish_signal_created(card)
            self._json_response(
                200,
                {
                    "ok": True,
                    "symbols_scanned": len(symbols),
                    "count": len(cards),
                    "events_published": published,
                    "cards": [c.to_dict() for c in cards],
                },
            )
        except Exception as exc:
            logger.exception("scan failed")
            self._json_response(500, {"ok": False, "error": str(exc)})

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

    cfg = build_scanner_config()
    market_data_service_url = os.getenv("MARKET_DATA_SERVICE_URL", "http://127.0.0.1:8083")
    fetcher = MarketDataClient(base_url=market_data_service_url)
    strategies = build_enabled_strategies(cfg)
    data_dir = os.getenv("DATA_DIR", "data")
    os.makedirs(data_dir, exist_ok=True)
    cache = SignalCache(os.path.join(data_dir, "signal_cache.json"))

    subscriber_urls = [
        os.getenv("NOTIFICATION_SERVICE_URL", "http://127.0.0.1:8081"),
        os.getenv("ANALYTICS_SERVICE_URL", "http://127.0.0.1:8084"),
    ]
    event_publisher = SignalEventPublisher(subscriber_urls=subscriber_urls)

    if not strategies:
        raise RuntimeError("No strategies enabled. Check enabled_strategies in config.")

    SignalEngineHandler.cfg = cfg
    SignalEngineHandler.fetcher = fetcher
    SignalEngineHandler.strategies = strategies
    SignalEngineHandler.cache = cache
    SignalEngineHandler.event_publisher = event_publisher

    host = os.getenv("SIGNAL_ENGINE_SERVICE_HOST", "0.0.0.0")
    port = int(os.getenv("SIGNAL_ENGINE_SERVICE_PORT", "8082"))

    server = ThreadingHTTPServer((host, port), SignalEngineHandler)
    logger.info("signal-engine-service listening on %s:%d", host, port)
    server.serve_forever()


if __name__ == "__main__":
    main()
