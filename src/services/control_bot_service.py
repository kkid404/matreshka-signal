from __future__ import annotations

import json
import logging
import os
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

from infrastructure.notification_client import NotificationClient
from infrastructure.signal_engine_client import SignalEngineClient
from telegram_notifier import TelegramNotifier
from strategies import ALL_STRATEGIES

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
logger = logging.getLogger("telegram-bot")

STRATEGY_DOCS: Dict[str, str] = {
    "matryoshka": "строгий отскок от уровня + свеча отказа",
    "ema_bounce": "отскок от EMA21 по тренду D1",
    "breakout": "пробой уровня с подтверждением объёмом",
    "engulfing": "паттерн поглощения рядом с уровнем",
    "momentum_break": "пробой локального диапазона по импульсу",
    "ema_cross": "свежий кросс EMA9/EMA21 по тренду D1",
}


class ReplayTelegramBot:
    def __init__(
        self,
        token: str,
        signal_engine_url: str,
        notifier: NotificationClient,
        allowed_user_ids: Optional[set[int]] = None,
    ):
        self.token = token
        self.signal_engine = SignalEngineClient(signal_engine_url)
        self.notifier = notifier
        self.allowed_user_ids = allowed_user_ids or set()
        self._offset = 0

        self.enabled_names: set[str] = set()
        self._refresh_enabled_names()

    def run(self) -> None:
        logger.info("Telegram replay bot started")
        while True:
            try:
                updates = self._get_updates(timeout=20)
                for upd in updates:
                    self._offset = max(self._offset, upd.get("update_id", 0) + 1)
                    self._handle_update(upd)
            except KeyboardInterrupt:
                logger.info("Telegram replay bot stopped by user")
                break
            except Exception:
                logger.exception("Bot loop error")
                time.sleep(1.0)

    def _get_updates(self, timeout: int = 20) -> List[Dict[str, Any]]:
        url = TelegramNotifier.API_URL.format(token=self.token, method="getUpdates")

        params = {
            "timeout": timeout,
            "offset": self._offset,
        }
        req = urllib.request.Request(
            f"{url}?{urllib.parse.urlencode(params)}",
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout + 5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        if not body.get("ok"):
            logger.error("getUpdates failed: %s", body)
            return []
        return body.get("result", [])

    def _handle_update(self, update: Dict[str, Any]) -> None:
        msg = update.get("message") or {}
        text = (msg.get("text") or "").strip()
        if not text.startswith("/"):
            return

        chat_id = str((msg.get("chat") or {}).get("id", ""))
        from_user = msg.get("from") or {}
        user_id = int(from_user.get("id", 0) or 0)

        if not chat_id:
            return

        if self.allowed_user_ids and user_id not in self.allowed_user_ids:
            self._send_text(chat_id, "⛔️ Доступ запрещён.")
            return

        cmd, args = self._parse_command(text)

        if cmd in ("start", "help"):
            self._send_text(chat_id, self._help_text())
            return

        if cmd == "strategies":
            self._send_text(chat_id, self._strategies_text())
            return

        if cmd == "replay":
            self._handle_replay(chat_id, args)
            return

        self._send_text(chat_id, "Неизвестная команда. Используй /help")

    def _handle_replay(self, chat_id: str, args: List[str]) -> None:
        if not self.enabled_names:
            self._send_text(chat_id, "❌ Нет активных стратегий. Проверь enabled_strategies.")
            return

        symbol = "BTCUSDT"
        lookback = 1200

        if len(args) >= 1:
            symbol = args[0].upper().replace("/", "").replace(":USDT", "")
        if len(args) >= 2:
            try:
                lookback = int(args[1])
            except ValueError:
                self._send_text(chat_id, "❌ LOOKBACK должен быть целым числом. Пример: /replay BTCUSDT 1200")
                return

        if lookback < 200 or lookback > 5000:
            self._send_text(chat_id, "❌ LOOKBACK должен быть в диапазоне 200..5000")
            return

        self._send_text(chat_id, f"📚 Запускаю replay: {symbol}, lookback={lookback} H4 ...")

        cards = self.signal_engine.replay_run(symbol=symbol, lookback=lookback)

        if not cards:
            self._send_text(chat_id, f"ℹ️ {symbol}: в истории не найдено сигналов по активным стратегиям.")
            return

        self._send_text(chat_id, f"✅ {symbol}: найдено {len(cards)} стратегий с последним сигналом. Отправляю карточки...")

        sent = 0
        for card in cards:
            if self.notifier.send_signal(card, chat_id=chat_id):
                sent += 1
            time.sleep(0.2)

        self._send_text(chat_id, f"📤 Отправлено карточек: {sent}/{len(cards)}")

    def _send_text(self, chat_id: str, text: str) -> None:
        self.notifier.send_text(text, chat_id=chat_id)

    def _refresh_enabled_names(self) -> None:
        payload = self.signal_engine.strategies()
        enabled = payload.get("enabled", []) if payload.get("ok") else []
        self.enabled_names = {str(name) for name in enabled}

    @staticmethod
    def _parse_command(text: str) -> Tuple[str, List[str]]:
        parts = text.split()
        cmd = parts[0].lstrip("/").split("@")[0].lower()
        return cmd, parts[1:]

    @staticmethod
    def _help_text() -> str:
        return (
            "🤖 <b>Matryoshka Replay Bot</b>\n\n"
            "Команды:\n"
            "/start — помощь\n"
            "/help — помощь\n"
            "/strategies — список стратегий и их статус\n"
            "/replay SYMBOL LOOKBACK — прогон истории\n\n"
            "Что значит /replay:\n"
            "• <b>SYMBOL</b> — тикер фьючерса, напр. BTCUSDT, SOLUSDT\n"
            "• <b>LOOKBACK</b> — сколько H4 свечей взять из истории\n"
            "  (рекомендуется 800..2000, по умолчанию 1200)\n\n"
            "Примеры:\n"
            "<code>/replay BTCUSDT 1200</code>\n"
            "<code>/replay SOLUSDT 1500</code>"
        )

    def _strategies_text(self) -> str:
        lines = ["🧩 <b>Стратегии:</b>", ""]
        for name in ALL_STRATEGIES.keys():
            enabled = name in self.enabled_names
            status = "✅ ON" if enabled else "⚪ OFF"
            desc = STRATEGY_DOCS.get(name, "описание не задано")
            lines.append(f"• <b>{name}</b> — {status}")
            lines.append(f"  {desc}")
        lines.append("")
        lines.append("Изменение состава стратегий сейчас делается в src/core/config.py → enabled_strategies")
        return "\n".join(lines)


def _parse_allowed_users(raw: str) -> set[int]:
    allowed: set[int] = set()
    for item in (raw or "").split(","):
        s = item.strip()
        if not s:
            continue
        try:
            allowed.add(int(s))
        except ValueError:
            logger.warning("Skipping invalid TELEGRAM_ALLOWED_USER_IDS entry: %s", s)
    return allowed


def main() -> None:
    load_dotenv()
    log_level = logging.DEBUG if os.getenv("BOT_DEBUG", "false").lower() in ("1", "true", "yes") else logging.INFO
    logging.basicConfig(level=log_level, format=LOG_FORMAT)
    logging.getLogger("ccxt").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")

    notification_service_url = os.getenv("NOTIFICATION_SERVICE_URL", "http://notification-service:8081")
    signal_engine_service_url = os.getenv("SIGNAL_ENGINE_SERVICE_URL", "http://signal-engine:8082")
    notifier = NotificationClient(
        base_url=notification_service_url,
        default_bot_token=token,
        enabled=True,
    )

    allowed = _parse_allowed_users(os.getenv("TELEGRAM_ALLOWED_USER_IDS", ""))
    bot = ReplayTelegramBot(
        token=token,
        signal_engine_url=signal_engine_service_url,
        notifier=notifier,
        allowed_user_ids=allowed,
    )
    bot.run()


if __name__ == "__main__":
    main()
