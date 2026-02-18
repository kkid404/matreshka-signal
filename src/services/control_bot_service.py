from __future__ import annotations

import json
import logging
import math
import os
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

from core.position_sizing import calculate_position_size_for_profile
from core.risk_profile import RiskProfile, RiskProfileStore
from infrastructure.notification_client import NotificationClient
from infrastructure.signal_engine_client import SignalEngineClient
from telegram_notifier import TelegramNotifier
from strategies import ALL_STRATEGIES
from core.models import SignalCard

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
        risk_profiles: Optional[RiskProfileStore] = None,
        default_qty_step: float = 0.0,
        default_min_qty: float = 0.0,
        default_min_notional: float = 0.0,
    ):
        self.token = token
        self.signal_engine = SignalEngineClient(signal_engine_url)
        self.notifier = notifier
        self.allowed_user_ids = allowed_user_ids or set()
        self.risk_profiles = risk_profiles or RiskProfileStore()
        self.default_qty_step = default_qty_step
        self.default_min_qty = default_min_qty
        self.default_min_notional = default_min_notional
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
            self._handle_replay(chat_id, user_id, args)
            return

        if cmd == "risk_profile":
            self._handle_risk_profile(chat_id, user_id)
            return

        if cmd == "set_budget":
            self._handle_set_budget(chat_id, user_id, args)
            return

        if cmd == "set_risk":
            self._handle_set_risk(chat_id, user_id, args)
            return

        if cmd == "set_limits":
            self._handle_set_limits(chat_id, user_id, args)
            return

        if cmd == "risk_help":
            self._send_text(chat_id, self._risk_help_text())
            return

        self._send_text(chat_id, "Неизвестная команда. Используй /help")

    def _handle_replay(self, chat_id: str, user_id: int, args: List[str]) -> None:
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
            if self._send_signal_with_risk(chat_id=chat_id, user_id=user_id, card=card):
                sent += 1
            time.sleep(0.2)

        self._send_text(chat_id, f"📤 Отправлено карточек: {sent}/{len(cards)}")

    def _handle_risk_profile(self, chat_id: str, user_id: int) -> None:
        profile = self.risk_profiles.get_or_create_default(user_id)
        self._send_text(chat_id, self._risk_profile_text(profile))

    def _handle_set_budget(self, chat_id: str, user_id: int, args: List[str]) -> None:
        if len(args) != 1:
            self._send_text(chat_id, "❌ Использование: /set_budget &lt;amount&gt;. Пример: /set_budget 1000")
            return
        try:
            budget = float(args[0])
        except ValueError:
            self._send_text(chat_id, "❌ budget должен быть числом. Пример: /set_budget 1000")
            return

        profile = self.risk_profiles.get_or_create_default(user_id)
        profile.budget_usdt = budget
        try:
            self.risk_profiles.upsert(profile)
        except ValueError as exc:
            self._send_text(chat_id, self._friendly_validation_error(exc))
            return
        self._send_text(chat_id, f"✅ Budget обновлён: {profile.budget_usdt:.2f} USDT")

    def _handle_set_risk(self, chat_id: str, user_id: int, args: List[str]) -> None:
        if len(args) != 1:
            self._send_text(chat_id, "❌ Использование: /set_risk &lt;percent&gt;. Пример: /set_risk 1.0")
            return
        try:
            risk = float(args[0])
        except ValueError:
            self._send_text(chat_id, "❌ risk % должен быть числом. Пример: /set_risk 1.0")
            return

        profile = self.risk_profiles.get_or_create_default(user_id)
        profile.risk_per_trade_pct = risk
        try:
            self.risk_profiles.upsert(profile)
        except ValueError as exc:
            self._send_text(chat_id, self._friendly_validation_error(exc))
            return
        self._send_text(chat_id, f"✅ Risk per trade обновлён: {profile.risk_per_trade_pct:.2f}%")

    def _handle_set_limits(self, chat_id: str, user_id: int, args: List[str]) -> None:
        if len(args) != 2:
            self._send_text(chat_id, "❌ Использование: /set_limits &lt;max_positions&gt; &lt;daily_risk_pct&gt;. Пример: /set_limits 3 4")
            return
        try:
            max_positions = int(args[0])
            daily_risk = float(args[1])
        except ValueError:
            self._send_text(chat_id, "❌ Неверный формат. Пример: /set_limits 3 4")
            return

        profile = self.risk_profiles.get_or_create_default(user_id)
        profile.max_open_positions = max_positions
        profile.daily_risk_limit_pct = daily_risk
        try:
            self.risk_profiles.upsert(profile)
        except ValueError as exc:
            self._send_text(chat_id, self._friendly_validation_error(exc))
            return
        self._send_text(
            chat_id,
            (
                "✅ Лимиты обновлены:\n"
                f"• max_open_positions: {profile.max_open_positions}\n"
                f"• daily_risk_limit_pct: {profile.daily_risk_limit_pct:.2f}%"
            ),
        )

    def _send_signal_with_risk(self, chat_id: str, user_id: int, card: SignalCard) -> bool:
        profile = self.risk_profiles.get_or_create_default(user_id)
        sizing = calculate_position_size_for_profile(
            profile=profile,
            entry_price=card.entry_price,
            stop_loss_price=card.stop_loss,
            qty_step=self.default_qty_step,
            min_qty=self.default_min_qty,
            min_notional=self.default_min_notional,
        )

        text = TelegramNotifier._format_card(card)
        text += "\n\n🛡 <b>Risk Management</b>"
        text += f"\n• Budget: <b>{profile.budget_usdt:.2f} USDT</b>"
        text += f"\n• Risk per trade: <b>{profile.risk_per_trade_pct:.2f}%</b>"

        if sizing.ok:
            text += f"\n• Risk amount: <b>{sizing.risk_amount_usdt:.2f} USDT</b>"
            text += f"\n• Recommended size: <b>{sizing.recommended_size:.6g}</b>"
            text += f"\n• Estimated loss at SL: <b>{sizing.estimated_loss_at_sl:.2f} USDT</b>"
        else:
            text += "\n• Sizing unavailable for this signal"
            text += f"\n• Reason: <code>{self._friendly_sizing_reason(sizing.reason)}</code>"

        return self.notifier.send_text(text, chat_id=chat_id)

    @staticmethod
    def _friendly_validation_error(exc: Exception) -> str:
        message = str(exc)
        if "budget_usdt" in message:
            return "❌ Бюджет должен быть конечным числом больше 0."
        if "risk_per_trade_pct" in message:
            return "❌ Риск на сделку должен быть в диапазоне 0.1..5.0%."
        if "max_open_positions" in message:
            return "❌ max_open_positions должен быть в диапазоне 1..20."
        if "daily_risk_limit_pct" in message:
            return "❌ daily_risk_limit_pct должен быть в диапазоне 0.1..20.0%."
        if "default_leverage" in message:
            return "❌ default_leverage должен быть больше 0."
        return f"❌ Ошибка валидации профиля: {message}"

    @staticmethod
    def _friendly_sizing_reason(reason: str) -> str:
        if not reason:
            return "position sizing failed"
        mapping = {
            "entry_price must be a finite number": "entry должен быть конечным числом",
            "stop_loss_price must be a finite number": "stop loss должен быть конечным числом",
            "budget_usdt must be a finite number": "budget должен быть конечным числом",
            "risk_per_trade_pct must be a finite number": "risk% должен быть конечным числом",
            "stop_distance must be > 0": "distance до SL должен быть > 0",
            "recommended_size is below min_qty": "расчётный размер ниже биржевого min_qty",
            "recommended_size is below min_notional": "расчётный размер ниже биржевого min_notional",
            "recommended_size is 0 after step rounding": "после округления по qty_step размер стал 0",
        }
        return mapping.get(reason, reason)

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
            "/replay SYMBOL LOOKBACK — прогон истории\n"
            "/risk_profile — показать риск-профиль\n"
            "/set_budget &lt;amount&gt; — обновить бюджет (USDT)\n"
            "/set_risk &lt;percent&gt; — обновить риск на сделку\n"
            "/set_limits &lt;max_positions&gt; &lt;daily_risk_pct&gt; — обновить лимиты\n"
            "/risk_help — справка по риск-менеджменту\n\n"
            "Что значит /replay:\n"
            "• <b>SYMBOL</b> — тикер фьючерса, напр. BTCUSDT, SOLUSDT\n"
            "• <b>LOOKBACK</b> — сколько H4 свечей взять из истории\n"
            "  (рекомендуется 800..2000, по умолчанию 1200)\n\n"
            "Примеры:\n"
            "<code>/replay BTCUSDT 1200</code>\n"
            "<code>/replay SOLUSDT 1500</code>\n"
            "<code>/set_budget 1000</code>\n"
            "<code>/set_risk 1.0</code>\n"
            "<code>/set_limits 3 4</code>"
        )

    @staticmethod
    def _risk_help_text() -> str:
        return (
            "🛡 <b>Risk Management (MVP)</b>\n\n"
            "Формула риска:\n"
            "risk_amount = budget * risk_per_trade_pct / 100\n"
            "size = risk_amount / |entry - sl|\n\n"
            "Команды:\n"
            "/risk_profile\n"
            "/set_budget &lt;amount&gt;\n"
            "/set_risk &lt;percent&gt;\n"
            "/set_limits &lt;max_positions&gt; &lt;daily_risk_pct&gt;\n"
        )

    @staticmethod
    def _risk_profile_text(profile: RiskProfile) -> str:
        return (
            "🛡 <b>Твой риск-профиль</b>\n\n"
            f"• budget_usdt: <b>{profile.budget_usdt:.2f}</b>\n"
            f"• risk_per_trade_pct: <b>{profile.risk_per_trade_pct:.2f}%</b>\n"
            f"• max_open_positions: <b>{profile.max_open_positions}</b>\n"
            f"• daily_risk_limit_pct: <b>{profile.daily_risk_limit_pct:.2f}%</b>\n"
            f"• active: <b>{'yes' if profile.is_active else 'no'}</b>"
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

    def _read_non_negative_env_float(name: str, default: float = 0.0) -> float:
        raw = os.getenv(name, "")
        if not raw.strip():
            return default
        try:
            value = float(raw)
        except ValueError:
            logger.warning("Invalid %s value '%s'; using default=%s", name, raw, default)
            return default
        if not math.isfinite(value) or value < 0:
            logger.warning("Invalid %s value '%s'; using default=%s", name, raw, default)
            return default
        return value

    risk_profiles_file = os.getenv("RISK_PROFILES_FILE", "data/risk_profiles.json")
    risk_profile_backend = os.getenv("RISK_PROFILE_BACKEND", "file").strip().lower() or "file"
    risk_profile_postgres_dsn = os.getenv("RISK_PROFILE_POSTGRES_DSN", "").strip() or os.getenv("POSTGRES_DSN", "").strip()
    risk_profiles = RiskProfileStore(
        file_path=risk_profiles_file,
        backend=risk_profile_backend,
        postgres_dsn=risk_profile_postgres_dsn,
    )
    default_qty_step = _read_non_negative_env_float("RISK_QTY_STEP", 0.0)
    default_min_qty = _read_non_negative_env_float("RISK_MIN_QTY", 0.0)
    default_min_notional = _read_non_negative_env_float("RISK_MIN_NOTIONAL", 0.0)

    allowed = _parse_allowed_users(os.getenv("TELEGRAM_ALLOWED_USER_IDS", ""))
    bot = ReplayTelegramBot(
        token=token,
        signal_engine_url=signal_engine_service_url,
        notifier=notifier,
        allowed_user_ids=allowed,
        risk_profiles=risk_profiles,
        default_qty_step=default_qty_step,
        default_min_qty=default_min_qty,
        default_min_notional=default_min_notional,
    )
    bot.run()


if __name__ == "__main__":
    main()
