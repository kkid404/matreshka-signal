"""Tests for SignalCache file and Redis backends."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.cache import SignalCache


class FakeRedisClient:
    def __init__(self):
        self.storage = {}

    def exists(self, key: str) -> int:
        return 1 if key in self.storage else 0

    def set(self, key: str, value: str) -> None:
        self.storage[key] = value

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.storage[key] = (value, ttl)


class BrokenRedisClient:
    def exists(self, key: str) -> int:
        raise RuntimeError("redis down")

    def set(self, key: str, value: str) -> None:
        raise RuntimeError("redis down")

    def setex(self, key: str, ttl: int, value: str) -> None:
        raise RuntimeError("redis down")


def test_file_cache_persists_seen_keys(tmp_path):
    cache_path = tmp_path / "signal_cache.json"

    cache = SignalCache(cache_file=str(cache_path))
    assert cache.is_new("BTCUSDT", "2025-01-01T00:00:00+00:00", "LONG") is True

    cache.mark("BTCUSDT", "2025-01-01T00:00:00+00:00", "LONG")
    assert cache.is_new("BTCUSDT", "2025-01-01T00:00:00+00:00", "LONG") is False

    cache2 = SignalCache(cache_file=str(cache_path))
    assert cache2.is_new("BTCUSDT", "2025-01-01T00:00:00+00:00", "LONG") is False

    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    assert payload["seen"]


def test_redis_cache_with_ttl_marks_and_detects_duplicates(tmp_path):
    fake_redis = FakeRedisClient()
    cache = SignalCache(
        cache_file=str(tmp_path / "signal_cache.json"),
        redis_client=fake_redis,
        redis_key_prefix="sig",
        redis_ttl_seconds=60,
    )

    symbol = "ETHUSDT"
    ts = "2025-01-02T00:00:00+00:00"
    direction = "SHORT"

    assert cache.is_new(symbol, ts, direction) is True
    cache.mark(symbol, ts, direction)
    assert cache.is_new(symbol, ts, direction) is False

    assert "sig:ETHUSDT|2025-01-02T00:00:00+00:00|SHORT" in fake_redis.storage


def test_fallback_to_file_cache_when_redis_fails(tmp_path):
    cache_path = tmp_path / "signal_cache.json"
    cache = SignalCache(
        cache_file=str(cache_path),
        redis_client=BrokenRedisClient(),
        redis_key_prefix="sig",
    )

    symbol = "SOLUSDT"
    ts = "2025-01-03T00:00:00+00:00"
    direction = "LONG"

    assert cache.is_new(symbol, ts, direction) is True
    cache.mark(symbol, ts, direction)
    assert cache.is_new(symbol, ts, direction) is False

    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    assert payload["seen"]
