"""Simple in-memory + file-backed signal cache to avoid duplicate alerts."""

from __future__ import annotations

import json
import os
from typing import Set

_CACHE_FILE = "signal_cache.json"


class SignalCache:
    """Tracks emitted signals so the scanner does not repeat them."""

    def __init__(self, cache_file: str = _CACHE_FILE):
        self._file = cache_file
        self._seen: Set[str] = set()
        self._load()

    def is_new(self, symbol: str, signal_time_iso: str, direction: str) -> bool:
        key = self._key(symbol, signal_time_iso, direction)
        return key not in self._seen

    def mark(self, symbol: str, signal_time_iso: str, direction: str) -> None:
        key = self._key(symbol, signal_time_iso, direction)
        self._seen.add(key)
        self._save()

    @staticmethod
    def _key(symbol: str, signal_time_iso: str, direction: str) -> str:
        return f"{symbol}|{signal_time_iso}|{direction}"

    def _load(self) -> None:
        if os.path.exists(self._file):
            try:
                with open(self._file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._seen = set(data.get("seen", []))
            except Exception:
                self._seen = set()

    def _save(self) -> None:
        with open(self._file, "w", encoding="utf-8") as f:
            json.dump({"seen": list(self._seen)}, f)
