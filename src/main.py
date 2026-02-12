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
from datetime import datetime, timezone
from typing import List

from dotenv import load_dotenv

from config import ScannerConfig, TelegramConfig
from data_fetcher import DataFetcher
from signal_detector import scan_symbol
from probability import calculate_probability
from levels import get_manual_levels, detect_swing_highs_lows, cluster_levels
from output import print_signal_card, print_signals_table, save_signals_json, save_signals_csv
from cache import SignalCache
from models import SignalCard
from telegram_notifier import TelegramNotifier

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
logger = logging.getLogger("matryoshka")


def build_config() -> ScannerConfig:
    """Build default config.  Edit this function or load from YAML/JSON later."""
    load_dotenv()

    tg_cfg = TelegramConfig(
        enabled=os.getenv("TELEGRAM_ENABLED", "false").lower() in ("true", "1", "yes"),
        bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
    )

    return ScannerConfig(telegram=tg_cfg)


def resolve_symbols(cfg: ScannerConfig, fetcher: DataFetcher) -> List[str]:
    """Resolve the list of symbols to scan based on symbols_mode."""
    flt = cfg.symbol_filter

    if cfg.symbols_mode == "manual":
        return cfg.symbols

    if cfg.symbols_mode == "top_n":
        return fetcher.get_top_usdt_perpetuals(
            top_n=cfg.top_n,
            min_volume_24h=flt.min_volume_24h,
            exclude=flt.exclude,
        )

    # "all"
    return fetcher.get_all_usdt_perpetuals(
        min_volume_24h=flt.min_volume_24h,
        exclude=flt.exclude,
    )


_SYMBOL_THROTTLE = 0.35  # seconds between symbols to avoid rate limits


def run_scan(
    cfg: ScannerConfig,
    fetcher: DataFetcher,
    cache: SignalCache,
    symbols: List[str],
) -> List[SignalCard]:
    """Execute one full scan across all configured symbols."""
    signals: List[SignalCard] = []
    total = len(symbols)

    for i, symbol in enumerate(symbols, 1):
        if i % 50 == 0 or i == 1:
            logger.info("Progress: %d/%d symbols …", i, total)
        logger.info("Scanning %s …", symbol)
        try:
            # Fetch D1 candles for context
            d1_candles = fetcher.fetch_candles(
                symbol, cfg.context.timeframe, limit=cfg.context.lookback_bars,
            )
            # Fetch H4 candles for setup + probability backtest
            h4_limit = max(cfg.setup.lookback_bars, cfg.probability.lookback_bars)
            h4_candles = fetcher.fetch_candles(
                symbol, cfg.setup.timeframe, limit=h4_limit,
            )

            if len(h4_candles) < 30:
                logger.warning("%s: not enough H4 data (%d candles)", symbol, len(h4_candles))
                continue

            # Detect signal
            card = scan_symbol(symbol, d1_candles, h4_candles, cfg)
            if card is None:
                logger.info("%s: no signal", symbol)
                continue

            # Deduplicate
            sig_time_iso = card.signal_candle_time.isoformat()
            if not cache.is_new(symbol, sig_time_iso, card.direction.value):
                logger.info("%s: signal already emitted, skipping", symbol)
                continue

            # Probability
            levels = _get_levels(symbol, h4_candles, cfg)
            prob = calculate_probability(symbol, h4_candles, d1_candles, levels, cfg)
            card.probability_percent = prob.probability_pct
            card.sample_size_n = prob.total
            card.low_sample = prob.low_sample

            # Output card
            print_signal_card(card)
            signals.append(card)
            cache.mark(symbol, sig_time_iso, card.direction.value)

        except Exception:
            logger.exception("Error scanning %s", symbol)

        time.sleep(_SYMBOL_THROTTLE)

    return signals


def _get_levels(symbol: str, h4_candles, cfg: ScannerConfig) -> List[float]:
    if cfg.levels_mode == "manual":
        return get_manual_levels(cfg.levels_manual, symbol)
    raw = detect_swing_highs_lows(h4_candles, order=5)
    return cluster_levels(raw, tolerance_pct=0.5)


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
    args = parser.parse_args()

    cfg = build_config()
    data_dir = os.getenv("DATA_DIR", "data")
    os.makedirs(data_dir, exist_ok=True)

    # --- logging setup ---
    log_level = logging.DEBUG if args.debug else logging.INFO
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if args.log_file:
        log_path = os.path.join(data_dir, args.log_file)
        handlers.append(logging.handlers.RotatingFileHandler(
            log_path, maxBytes=5_000_000, backupCount=3, encoding="utf-8",
        ))
    logging.basicConfig(level=log_level, format=LOG_FORMAT, handlers=handlers)
    cfg.output_json = os.path.join(data_dir, cfg.output_json)
    cfg.output_csv = os.path.join(data_dir, cfg.output_csv)

    fetcher = DataFetcher()  # no API key needed for public endpoints
    cache = SignalCache(os.path.join(data_dir, "signal_cache.json"))
    tg = TelegramNotifier(
        bot_token=cfg.telegram.bot_token,
        chat_id=cfg.telegram.chat_id,
        enabled=cfg.telegram.enabled,
    )

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
        chat_id = tg.fetch_chat_id()
        if not chat_id:
            logger.error("Не нашёл /start сообщение. Убедись что написал /start боту.")
            return
        # Save to .env
        _save_chat_id_to_env(chat_id)
        tg.chat_id = chat_id
        tg.send_text("✅ Matryoshka Scanner подключён! Сигналы будут приходить сюда.")
        logger.info("✅ chat_id=%s сохранён в .env. Тестовое сообщение отправлено!", chat_id)
        return

    if args.test_telegram:
        ok = tg.send_text("✅ Matryoshka Scanner — Telegram работает!")
        if ok:
            logger.info("Test message sent successfully!")
        else:
            logger.error("Failed to send test message. Check bot_token and chat_id in .env")
        return

    if args.daemon:
        while True:
            try:
                t0 = time.time()
                symbols = resolve_symbols(cfg, fetcher)
                logger.info("Scanning %d symbols …", len(symbols))
                signals = run_scan(cfg, fetcher, cache, symbols)
                if signals:
                    print_signals_table(signals)
                    save_signals_json(signals, cfg.output_json)
                    save_signals_csv(signals, cfg.output_csv)
                    sent = tg.send_signals(signals)
                    if sent:
                        logger.info("Sent %d signal(s) to Telegram", sent)
                elapsed = time.time() - t0
                logger.info("Scan completed in %.1f s — %d signal(s)", elapsed, len(signals))
                sleep_for = max(0, cfg.scan_interval_seconds - elapsed)
                logger.info("Next scan in %.0f s …", sleep_for)
                time.sleep(sleep_for)
            except KeyboardInterrupt:
                logger.info("Scanner stopped by user.")
                break
    else:
        symbols = resolve_symbols(cfg, fetcher)
        logger.info("Scanning %d symbols …", len(symbols))
        signals = run_scan(cfg, fetcher, cache, symbols)
        if signals:
            print_signals_table(signals)
            save_signals_json(signals, cfg.output_json)
            save_signals_csv(signals, cfg.output_csv)
            sent = tg.send_signals(signals)
            if sent:
                logger.info("Sent %d signal(s) to Telegram", sent)
        else:
            logger.info("No signals found.")


if __name__ == "__main__":
    main()
