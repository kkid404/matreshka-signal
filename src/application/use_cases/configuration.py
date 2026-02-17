from __future__ import annotations

import os

from dotenv import load_dotenv

from core.config import ScannerConfig, TelegramConfig


def build_scanner_config() -> ScannerConfig:
    """Build scanner config from environment variables."""
    load_dotenv()

    tg_cfg = TelegramConfig(
        enabled=os.getenv("TELEGRAM_ENABLED", "false").lower() in ("true", "1", "yes"),
        bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
    )

    return ScannerConfig(telegram=tg_cfg)
