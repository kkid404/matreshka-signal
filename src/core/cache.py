"""Signal cache to avoid duplicate alerts (file-backed with optional Redis backend)."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Set

try:
    import redis
except ImportError:  # pragma: no cover - optional dependency
    redis = None

_CACHE_FILE = "signal_cache.json"
_DEFAULT_REDIS_TTL_SECONDS = 7 * 24 * 60 * 60

logger = logging.getLogger(__name__)


class SignalCache:
    """Tracks emitted signals so the scanner does not repeat them."""

    def __init__(
        self,
        cache_file: str = _CACHE_FILE,
        redis_url: str = "",
        redis_key_prefix: str = "signal_cache",
        redis_ttl_seconds: int = _DEFAULT_REDIS_TTL_SECONDS,
        redis_client: Any = None,
    ):
        self._file = cache_file
        self._redis_key_prefix = redis_key_prefix or "signal_cache"
        self._redis_ttl_seconds = int(redis_ttl_seconds) if redis_ttl_seconds and redis_ttl_seconds > 0 else 0
        self._redis_client = None
        self._seen: Set[str] = set()
        self._load()

        if redis_client is not None:
            self._redis_client = redis_client
            logger.info("SignalCache backend: redis (injected client)")
            return

        if redis_url:
            self._init_redis(redis_url)

        logger.info("SignalCache backend: %s", "redis" if self._redis_client is not None else "file")

    def is_new(self, symbol: str, signal_time_iso: str, direction: str) -> bool:
        key = self._key(symbol, signal_time_iso, direction)
        if self._redis_client is not None:
            try:
                return not bool(self._redis_client.exists(self._redis_key(key)))
            except Exception as exc:
                self._disable_redis(exc)
        return key not in self._seen

    def mark(self, symbol: str, signal_time_iso: str, direction: str) -> None:
        key = self._key(symbol, signal_time_iso, direction)
        if self._redis_client is not None:
            try:
                redis_key = self._redis_key(key)
                if self._redis_ttl_seconds > 0:
                    self._redis_client.setex(redis_key, self._redis_ttl_seconds, "1")
                else:
                    self._redis_client.set(redis_key, "1")
                return
            except Exception as exc:
                self._disable_redis(exc)

        self._seen.add(key)
        self._save()

    @staticmethod
    def _key(symbol: str, signal_time_iso: str, direction: str) -> str:
        return f"{symbol}|{signal_time_iso}|{direction}"

    def _redis_key(self, key: str) -> str:
        return f"{self._redis_key_prefix}:{key}"

    def _init_redis(self, redis_url: str) -> None:
        if redis is None:
            logger.warning("redis package is not installed; falling back to file cache")
            return
        try:
            client = redis.Redis.from_url(redis_url, decode_responses=True)
            client.ping()
            self._redis_client = client
        except Exception as exc:
            logger.warning("Redis unavailable (%s); using file cache", exc)
            self._redis_client = None

    def _disable_redis(self, exc: Exception) -> None:
        logger.warning("Redis cache failed (%s); switched to file cache", exc)
        self._redis_client = None

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
