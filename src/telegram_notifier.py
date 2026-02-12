"""Telegram notification sender for the Matryoshka scanner."""

from __future__ import annotations

import logging
import urllib.request
import urllib.parse
import urllib.error
import json
from typing import List, Optional

from models import SignalCard

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Sends signal cards to a Telegram chat via Bot API (no external deps)."""

    API_URL = "https://api.telegram.org/bot{token}/{method}"

    def __init__(self, bot_token: str, chat_id: str, enabled: bool = True):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.enabled = enabled

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def send_signal(self, card: SignalCard) -> bool:
        """Format and send a single signal card. Returns True on success."""
        if not self.enabled:
            return False
        text = self._format_card(card)
        return self._send_message(text)

    def send_signals(self, cards: List[SignalCard]) -> int:
        """Send multiple signal cards. Returns count of successfully sent."""
        sent = 0
        for card in cards:
            if self.send_signal(card):
                sent += 1
        return sent

    def send_text(self, text: str) -> bool:
        """Send arbitrary text message."""
        if not self.enabled:
            return False
        return self._send_message(text)

    def fetch_chat_id(self) -> Optional[str]:
        """Call getUpdates and return the chat_id of the first /start message."""
        if not self.bot_token:
            logger.error("bot_token not set")
            return None
        url = self.API_URL.format(token=self.bot_token, method="getUpdates")
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            if not body.get("ok"):
                logger.error("getUpdates failed: %s", body)
                return None
            for update in body.get("result", []):
                msg = update.get("message", {})
                if msg.get("text", "").startswith("/start"):
                    chat_id = str(msg["chat"]["id"])
                    logger.info("Found chat_id: %s (user: %s)",
                                chat_id, msg["chat"].get("first_name", ""))
                    return chat_id
            return None
        except Exception as exc:
            logger.error("getUpdates error: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------

    @staticmethod
    def _format_card(card: SignalCard) -> str:
        direction_emoji = "\U0001f7e2" if card.direction.value == "LONG" else "\U0001f534"
        sample_warning = " \u26a0\ufe0f \u043c\u0430\u043b\u043e \u0434\u0430\u043d\u043d\u044b\u0445" if card.low_sample else ""

        lines = [
            f"{direction_emoji} <b>{card.symbol}</b> \u2014 <b>{card.direction.value}</b>",
            "",
            f"\u23f0 <b>\u0422\u0430\u0439\u043c\u0444\u0440\u0435\u0439\u043c:</b> {card.timeframe}",
            f"\U0001f4c5 <b>\u0421\u0438\u0433\u043d\u0430\u043b:</b> {card.signal_candle_time.strftime('%Y-%m-%d %H:%M UTC')}",
            f"\U0001f4cd <b>\u0423\u0440\u043e\u0432\u0435\u043d\u044c:</b> {card.level_price}",
            "",
            f"\u27a1\ufe0f <b>\u0412\u0445\u043e\u0434:</b> <code>{card.entry_price:.6g}</code>",
            f"\U0001f6d1 <b>\u0421\u0442\u043e\u043f-\u043b\u043e\u0441\u0441:</b> <code>{card.stop_loss:.6g}</code>",
            f"\U0001f3af <b>\u0422\u0435\u0439\u043a-\u043f\u0440\u043e\u0444\u0438\u0442:</b> <code>{card.take_profit:.6g}</code>",
            f"\U0001f4ca <b>RR:</b> 1:{card.rr_target}",
        ]

        if card.ladder:
            lines.append("")
            lines.append("<b>\U0001fa9c \u041b\u0435\u0441\u0435\u043d\u043a\u0430 TP:</b>")
            for step in card.ladder:
                be_note = " (\u0421\u041b \u2192 BE)" if step.move_sl_to_be else ""
                lines.append(f"  \u2022 {step.tp_rr}R \u2014 \u0437\u0430\u043a\u0440\u044b\u0442\u044c {step.close_pct*100:.0f}%{be_note}")

        lines.append("")
        lines.append(
            f"\U0001f4c8 <b>\u0412\u0435\u0440\u043e\u044f\u0442\u043d\u043e\u0441\u0442\u044c:</b> {card.probability_percent:.1f}% "
            f"(N={card.sample_size_n}{sample_warning})"
        )

        if card.tradingview_link:
            lines.append(f'\n\U0001f517 <a href="{card.tradingview_link}">\u0413\u0440\u0430\u0444\u0438\u043a TradingView</a>')

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # HTTP (stdlib only — no extra dependencies)
    # ------------------------------------------------------------------

    def _send_message(self, text: str) -> bool:
        """Send a message via Telegram Bot API using urllib (no requests needed)."""
        if not self.bot_token or not self.chat_id:
            logger.warning("Telegram not configured (missing bot_token or chat_id)")
            return False

        url = self.API_URL.format(token=self.bot_token, method="sendMessage")
        payload = json.dumps({
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                if body.get("ok"):
                    logger.debug("Telegram message sent successfully")
                    return True
                else:
                    logger.error("Telegram API error: %s", body)
                    return False
        except urllib.error.HTTPError as exc:
            logger.error("Telegram HTTP error %d: %s", exc.code, exc.read().decode())
            return False
        except Exception as exc:
            logger.error("Telegram send failed: %s", exc)
            return False
