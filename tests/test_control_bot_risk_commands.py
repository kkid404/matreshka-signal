"""Tests for risk profile commands in Telegram control bot."""

from datetime import datetime, timezone
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.risk_profile import RiskProfileStore
from core.models import Direction, SignalCard
from services.control_bot_service import ReplayTelegramBot


class DummyNotifier:
    def __init__(self):
        self.sent = []

    def send_text(self, text: str, chat_id: str = ""):
        self.sent.append((chat_id, text))
        return True

    def send_signal(self, card, chat_id: str = ""):
        return True


def _build_update(text: str, user_id: int = 100, chat_id: int = 900):
    return {
        "update_id": 1,
        "message": {
            "text": text,
            "chat": {"id": chat_id},
            "from": {"id": user_id},
        },
    }


def _make_bot(tmp_path):
    store = RiskProfileStore(file_path=str(tmp_path / "risk_profiles.json"))
    notifier = DummyNotifier()

    original_refresh = ReplayTelegramBot._refresh_enabled_names
    ReplayTelegramBot._refresh_enabled_names = lambda self: setattr(self, "enabled_names", set())
    try:
        bot = ReplayTelegramBot(
            token="test",
            signal_engine_url="http://127.0.0.1:9999",
            notifier=notifier,
            risk_profiles=store,
        )
    finally:
        ReplayTelegramBot._refresh_enabled_names = original_refresh
    return bot, notifier, store


def test_set_budget_command_updates_profile(tmp_path):
    bot, notifier, store = _make_bot(tmp_path)

    bot._handle_update(_build_update("/set_budget 1500", user_id=42, chat_id=123))

    profile = store.get(42)
    assert profile is not None
    assert profile.budget_usdt == 1500.0
    assert notifier.sent[-1][0] == "123"
    assert "Budget обновлён" in notifier.sent[-1][1]


def test_set_limits_invalid_command_returns_error(tmp_path):
    bot, notifier, _ = _make_bot(tmp_path)

    bot._handle_update(_build_update("/set_limits 0 4", user_id=42, chat_id=123))

    assert notifier.sent
    assert notifier.sent[-1][0] == "123"
    assert "max_open_positions должен быть в диапазоне 1..20" in notifier.sent[-1][1]


def _sample_card(stop_loss: float = 95.0) -> SignalCard:
    return SignalCard(
        symbol="BTCUSDT",
        direction=Direction.LONG,
        timeframe="H4",
        signal_candle_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
        level_price=100.0,
        entry_price=100.0,
        stop_loss=stop_loss,
        take_profit=115.0,
        rr_target=3.0,
        probability_percent=57.5,
        sample_size_n=120,
        strategy_name="matryoshka",
    )


def test_send_signal_with_risk_contains_recommended_size(tmp_path):
    bot, notifier, store = _make_bot(tmp_path)
    profile = store.get_or_create_default(42)
    profile.budget_usdt = 1000.0
    profile.risk_per_trade_pct = 1.0
    store.upsert(profile)

    ok = bot._send_signal_with_risk(chat_id="123", user_id=42, card=_sample_card(stop_loss=95.0))

    assert ok is True
    sent_text = notifier.sent[-1][1]
    assert "Risk Management" in sent_text
    assert "Risk amount" in sent_text
    assert "Recommended size" in sent_text
    assert "2" in sent_text


def test_replay_fallback_when_sizing_unavailable(tmp_path):
    bot, notifier, store = _make_bot(tmp_path)
    profile = store.get_or_create_default(42)
    profile.budget_usdt = 1000.0
    profile.risk_per_trade_pct = 1.0
    store.upsert(profile)

    bot.enabled_names = {"matryoshka"}
    bot.signal_engine.replay_run = lambda symbol, lookback: [_sample_card(stop_loss=100.0)]

    bot._handle_update(_build_update("/replay BTCUSDT 1200", user_id=42, chat_id=123))

    all_messages = [text for _, text in notifier.sent]
    merged = "\n".join(all_messages)
    assert "Sizing unavailable for this signal" in merged
    assert "distance до SL должен быть > 0" in merged


def test_send_signal_with_risk_respects_min_qty_limit(tmp_path):
    bot, notifier, store = _make_bot(tmp_path)
    bot.default_min_qty = 3.0

    profile = store.get_or_create_default(42)
    profile.budget_usdt = 1000.0
    profile.risk_per_trade_pct = 1.0
    store.upsert(profile)

    ok = bot._send_signal_with_risk(chat_id="123", user_id=42, card=_sample_card(stop_loss=95.0))

    assert ok is True
    sent_text = notifier.sent[-1][1]
    assert "Sizing unavailable for this signal" in sent_text
    assert "ниже биржевого min_qty" in sent_text


def test_help_text_is_html_safe_for_angle_bracket_args():
    help_text = ReplayTelegramBot._help_text()
    risk_help_text = ReplayTelegramBot._risk_help_text()

    assert "<amount>" not in help_text
    assert "<percent>" not in help_text
    assert "<max_positions>" not in help_text

    assert "&lt;amount&gt;" in help_text
    assert "&lt;percent&gt;" in help_text
    assert "&lt;max_positions&gt;" in help_text

    assert "<amount>" not in risk_help_text
    assert "<percent>" not in risk_help_text
    assert "<daily_risk_pct>" not in risk_help_text

    assert "&lt;amount&gt;" in risk_help_text
    assert "&lt;percent&gt;" in risk_help_text
    assert "&lt;daily_risk_pct&gt;" in risk_help_text


def test_set_limits_usage_text_is_html_safe(tmp_path):
    bot, notifier, _ = _make_bot(tmp_path)

    bot._handle_update(_build_update("/set_limits 3", user_id=42, chat_id=123))

    sent_text = notifier.sent[-1][1]
    assert "<max_positions>" not in sent_text
    assert "<daily_risk_pct>" not in sent_text
    assert "&lt;max_positions&gt;" in sent_text
    assert "&lt;daily_risk_pct&gt;" in sent_text
