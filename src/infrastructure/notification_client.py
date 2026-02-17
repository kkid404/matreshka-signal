from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Iterable, Optional

from core.models import SignalCard

logger = logging.getLogger(__name__)


class NotificationClient:
    """HTTP client for external notification-service."""

    def __init__(
        self,
        base_url: str,
        default_bot_token: str = "",
        default_chat_id: str = "",
        enabled: bool = True,
        timeout: int = 10,
    ):
        self.base_url = base_url.rstrip("/")
        self.default_bot_token = default_bot_token
        self.default_chat_id = default_chat_id
        self.enabled = enabled
        self.timeout = timeout

    def send_text(self, text: str, chat_id: str = "", bot_token: str = "") -> bool:
        if not self.enabled:
            return False
        payload = {
            "text": text,
            "chat_id": chat_id or self.default_chat_id,
            "bot_token": bot_token or self.default_bot_token,
        }
        body = self._post_json("/notify/text", payload)
        return bool(body.get("ok", False))

    def send_signal(self, card: SignalCard, chat_id: str = "", bot_token: str = "") -> bool:
        if not self.enabled:
            return False
        payload = {
            "card": card.to_dict(),
            "chat_id": chat_id or self.default_chat_id,
            "bot_token": bot_token or self.default_bot_token,
        }
        body = self._post_json("/notify/signal-card", payload)
        return bool(body.get("ok", False))

    def send_signals(self, cards: Iterable[SignalCard], chat_id: str = "", bot_token: str = "") -> int:
        sent = 0
        for card in cards:
            if self.send_signal(card, chat_id=chat_id, bot_token=bot_token):
                sent += 1
        return sent

    def fetch_chat_id(self, bot_token: str = "") -> Optional[str]:
        token = bot_token or self.default_bot_token
        if not token:
            return None
        body = self._get_json(f"/telegram/fetch-chat-id?bot_token={token}")
        if not body.get("ok"):
            return None
        chat_id = body.get("chat_id")
        return str(chat_id) if chat_id else None

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
        except urllib.error.HTTPError as exc:
            logger.error("notification-service HTTP %d on %s", exc.code, path)
        except Exception as exc:
            logger.error("notification-service error on %s: %s", path, exc)
        return {"ok": False}

    def _get_json(self, path: str) -> dict:
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            logger.error("notification-service HTTP %d on %s", exc.code, path)
        except Exception as exc:
            logger.error("notification-service error on %s: %s", path, exc)
        return {"ok": False}
