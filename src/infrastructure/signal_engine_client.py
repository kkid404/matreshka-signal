from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any, Dict, List

from infrastructure.signal_card_codec import signal_card_from_dict
from core.models import SignalCard

logger = logging.getLogger(__name__)


class SignalEngineClient:
    """HTTP client for signal-engine-service."""

    def __init__(self, base_url: str, timeout: int = 60):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def replay_run(self, symbol: str, lookback: int) -> List[SignalCard]:
        body = self._post_json("/replay/run", {"symbol": symbol, "lookback": lookback})
        if not body.get("ok"):
            return []
        cards_raw = body.get("cards", []) or []
        return [signal_card_from_dict(c) for c in cards_raw]

    def scan_run(self) -> List[SignalCard]:
        body = self._post_json("/scan/run", {})
        if not body.get("ok"):
            return []
        cards_raw = body.get("cards", []) or []
        return [signal_card_from_dict(c) for c in cards_raw]

    def strategies(self) -> Dict[str, Any]:
        return self._get_json("/strategies")

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
            logger.error("signal-engine HTTP %d on %s", exc.code, path)
        except Exception as exc:
            logger.error("signal-engine error on %s: %s", path, exc)
        return {"ok": False}

    def _get_json(self, path: str) -> dict:
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            logger.error("signal-engine HTTP %d on %s", exc.code, path)
        except Exception as exc:
            logger.error("signal-engine error on %s: %s", path, exc)
        return {"ok": False}
