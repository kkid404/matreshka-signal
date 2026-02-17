from __future__ import annotations

import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

from infrastructure.signal_card_codec import signal_card_from_dict
from telegram_notifier import TelegramNotifier

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
logger = logging.getLogger("notification-service")


class NotificationHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._json_response(200, {"ok": True, "service": "notification"})
            return

        if parsed.path == "/telegram/fetch-chat-id":
            qs = parse_qs(parsed.query)
            bot_token = (qs.get("bot_token") or [""])[0] or os.getenv("TELEGRAM_BOT_TOKEN", "")
            if not bot_token:
                self._json_response(400, {"ok": False, "error": "bot_token is required"})
                return
            notifier = TelegramNotifier(bot_token=bot_token, chat_id="", enabled=True)
            chat_id = notifier.fetch_chat_id()
            self._json_response(200, {"ok": bool(chat_id), "chat_id": chat_id})
            return

        self._json_response(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        try:
            payload = self._read_json_body()
        except ValueError:
            self._json_response(400, {"ok": False, "error": "invalid json body"})
            return

        if self.path == "/events/signal-created":
            raw_card = payload.get("card")
            if not isinstance(raw_card, dict):
                self._json_response(400, {"ok": False, "error": "card dict is required"})
                return
            notifier = self._build_notifier(payload)
            card = signal_card_from_dict(raw_card)
            self._json_response(200, {"ok": notifier.send_signal(card)})
            return

        if self.path == "/notify/text":
            text = str(payload.get("text", "")).strip()
            notifier = self._build_notifier(payload)
            if not text:
                self._json_response(400, {"ok": False, "error": "text is required"})
                return
            self._json_response(200, {"ok": notifier.send_text(text)})
            return

        if self.path == "/notify/signal-card":
            raw_card = payload.get("card")
            if not isinstance(raw_card, dict):
                self._json_response(400, {"ok": False, "error": "card dict is required"})
                return
            notifier = self._build_notifier(payload)
            card = signal_card_from_dict(raw_card)
            self._json_response(200, {"ok": notifier.send_signal(card)})
            return

        self._json_response(404, {"ok": False, "error": "not found"})

    def _build_notifier(self, payload: dict) -> TelegramNotifier:
        bot_token = str(payload.get("bot_token", "") or os.getenv("TELEGRAM_BOT_TOKEN", ""))
        chat_id = str(payload.get("chat_id", "") or os.getenv("TELEGRAM_CHAT_ID", ""))
        return TelegramNotifier(bot_token=bot_token, chat_id=chat_id, enabled=True)

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

    host = os.getenv("NOTIFICATION_SERVICE_HOST", "0.0.0.0")
    port = int(os.getenv("NOTIFICATION_SERVICE_PORT", "8081"))

    server = ThreadingHTTPServer((host, port), NotificationHandler)
    logger.info("notification-service listening on %s:%d", host, port)
    server.serve_forever()


if __name__ == "__main__":
    main()
