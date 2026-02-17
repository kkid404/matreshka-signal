"""Matryoshka Scanner — entry point.

Usage:
    python main.py              # single scan
    python main.py --daemon     # continuous scanning every 5 min
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import sys
import time
from typing import List

from application.use_cases.configuration import build_scanner_config
from core.config import ScannerConfig
from core.output import print_signal_card, print_signals_table, save_signals_json, save_signals_csv
from infrastructure.notification_client import NotificationClient
from infrastructure.signal_engine_client import SignalEngineClient

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
logger = logging.getLogger("matryoshka")


def build_config() -> ScannerConfig:
    """Build default config.  Edit this function or load from YAML/JSON later."""
    return build_scanner_config()


def _save_chat_id_to_env(chat_id: str) -> None:
    """Write TELEGRAM_CHAT_ID into .env file (create or update)."""
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    lines: List[str] = []
    found = False

    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for i, line in enumerate(lines):
            if line.startswith("TELEGRAM_CHAT_ID"):
                lines[i] = f"TELEGRAM_CHAT_ID={chat_id}\n"
                found = True
                break

    if not found:
        lines.append(f"TELEGRAM_CHAT_ID={chat_id}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    logger.info("Saved TELEGRAM_CHAT_ID=%s to %s", chat_id, env_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Matryoshka Signal Scanner")
    parser.add_argument("--daemon", action="store_true", help="Run continuously")
    parser.add_argument("--debug", action="store_true", help="Verbose debug logging")
    parser.add_argument("--test-telegram", action="store_true", help="Send test message and exit")
    parser.add_argument("--setup-telegram", action="store_true", help="Auto-detect chat_id from /start")
    parser.add_argument("--log-file", type=str, default="", help="Save logs to file in data/ (e.g. scanner.log)")
    parser.add_argument("--replay-symbol", type=str, default="", help="Replay one symbol history and send one latest signal per strategy")
    parser.add_argument("--replay-lookback", type=int, default=1200, help="H4 candles to scan in replay mode")
    args = parser.parse_args()

    cfg = build_config()
    data_dir = os.getenv("DATA_DIR", "data")
    os.makedirs(data_dir, exist_ok=True)

    # --- logging setup ---
    log_level = logging.DEBUG if args.debug else logging.INFO
    handlers: list[logging.Handler] = [logging.StreamHandler(stream=sys.stdout)]
    if args.log_file:
        log_path = os.path.join(data_dir, args.log_file)
        handlers.append(logging.handlers.RotatingFileHandler(
            log_path, maxBytes=5_000_000, backupCount=3, encoding="utf-8",
        ))
    logging.basicConfig(level=log_level, format=LOG_FORMAT, handlers=handlers)
    # Keep third-party HTTP debug noise out of the main log.
    logging.getLogger("ccxt").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    cfg.output_json = os.path.join(data_dir, cfg.output_json)
    cfg.output_csv = os.path.join(data_dir, cfg.output_csv)

    notification_service_url = os.getenv("NOTIFICATION_SERVICE_URL", "http://127.0.0.1:8081")
    signal_engine_service_url = os.getenv("SIGNAL_ENGINE_SERVICE_URL", "http://127.0.0.1:8082")

    notifier = NotificationClient(
        base_url=notification_service_url,
        default_bot_token=cfg.telegram.bot_token,
        default_chat_id=cfg.telegram.chat_id,
        enabled=cfg.telegram.enabled,
    )
    signal_engine = SignalEngineClient(base_url=signal_engine_service_url)

    logger.info("=== Matryoshka Scanner started ===")
    logger.info("Symbols mode: %s", cfg.symbols_mode)
    logger.info("Mode: %s", "daemon" if args.daemon else "single scan")
    if cfg.telegram.enabled:
        logger.info("Telegram: ON (chat_id=%s)", cfg.telegram.chat_id)
    else:
        logger.info("Telegram: OFF")

    if args.setup_telegram:
        if not cfg.telegram.bot_token:
            logger.error("Сначала впиши TELEGRAM_BOT_TOKEN в .env")
            return
        print("\nНапиши /start твоему боту в Telegram, затем нажми Enter здесь...")
        input()
        chat_id = notifier.fetch_chat_id()
        if not chat_id:
            logger.error("Не нашёл /start сообщение (через notification-service). Убедись что написал /start боту.")
            return
        # Save to .env
        _save_chat_id_to_env(chat_id)
        notifier.default_chat_id = chat_id
        notifier.send_text("✅ Matryoshka Scanner подключён! Сигналы будут приходить сюда.")
        logger.info("✅ chat_id=%s сохранён в .env. Тестовое сообщение отправлено!", chat_id)
        return

    if args.test_telegram:
        ok = notifier.send_text("✅ Matryoshka Scanner — Telegram работает!")
        if ok:
            logger.info("Test message sent successfully!")
        else:
            logger.error("Failed to send test message via notification-service. Check service URL, bot_token and chat_id")
        return

    if args.replay_symbol:
        symbol = args.replay_symbol.upper().replace("/", "").replace(":USDT", "")
        logger.info("Replay mode: symbol=%s, lookback=%d H4", symbol, args.replay_lookback)
        cards = signal_engine.replay_run(symbol=symbol, lookback=args.replay_lookback)

        if not cards:
            logger.info("%s: no historical signals found for selected strategies", symbol)
            if notifier.enabled:
                notifier.send_text(f"ℹ️ {symbol}: в истории не найдено сигналов по активным стратегиям.")
            return

        print_signals_table(cards)
        logger.info("Replay found %d strategy signal(s)", len(cards))

        if notifier.enabled:
            notifier.send_text(f"📚 Replay {symbol}: отправляю по 1 последнему сигналу на каждую стратегию ({len(cards)} шт.)")
            sent = 0
            for card in cards:
                if notifier.send_signal(card):
                    sent += 1
                time.sleep(0.25)
            logger.info("Replay: sent %d/%d cards to Telegram", sent, len(cards))
        else:
            logger.warning("Replay complete, but Telegram is disabled")
        return

    if args.daemon:
        while True:
            try:
                t0 = time.time()
                logger.info("Requesting scan from signal-engine-service …")
                signals = signal_engine.scan_run()
                if signals:
                    for card in signals:
                        print_signal_card(card)
                    print_signals_table(signals)
                    save_signals_json(signals, cfg.output_json)
                    save_signals_csv(signals, cfg.output_csv)
                    logger.info("Signals delivered via signal.created subscribers")
                elapsed = time.time() - t0
                logger.info("Scan completed in %.1f s — %d signal(s)", elapsed, len(signals))
                sleep_for = max(0, cfg.scan_interval_seconds - elapsed)
                logger.info("Next scan in %.0f s …", sleep_for)
                time.sleep(sleep_for)
            except KeyboardInterrupt:
                logger.info("Scanner stopped by user.")
                break
    else:
        logger.info("Requesting single scan from signal-engine-service …")
        signals = signal_engine.scan_run()
        if signals:
            for card in signals:
                print_signal_card(card)
            print_signals_table(signals)
            save_signals_json(signals, cfg.output_json)
            save_signals_csv(signals, cfg.output_csv)
            logger.info("Signals delivered via signal.created subscribers")
        else:
            logger.info("No signals found.")


if __name__ == "__main__":
    main()
