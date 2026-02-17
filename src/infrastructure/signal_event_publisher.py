from __future__ import annotations

import json
import logging
import urllib.request
from datetime import datetime, timezone
from typing import Iterable

from core.models import SignalCard

logger = logging.getLogger(__name__)


class SignalEventPublisher:
    """Publishes signal.created events to multiple subscribers."""

    def __init__(self, subscriber_urls: Iterable[str], timeout: int = 10):
        self.subscriber_urls = [u.rstrip("/") for u in subscriber_urls if u]
        self.timeout = timeout

    def publish_signal_created(self, card: SignalCard) -> int:
        payload = {
            "event": "signal.created",
            "emitted_at": datetime.now(timezone.utc).isoformat(),
            "card": card.to_dict(),
        }
        sent = 0
        for base_url in self.subscriber_urls:
            url = f"{base_url}/events/signal-created"
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                    if body.get("ok"):
                        sent += 1
            except Exception as exc:
                logger.error("failed to publish signal.created to %s: %s", base_url, exc)
        return sent
