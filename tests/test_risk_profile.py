"""Tests for risk profile model and file-backed storage."""

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.risk_profile import RiskProfile, RiskProfileStore


class FakePgCursor:
    def __init__(self, storage):
        self.storage = storage
        self._result = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        q = " ".join(str(query).split()).lower()
        if q.startswith("create table"):
            return
        if q.startswith("select"):
            user_id = int(params[0])
            self._result = self.storage.get(user_id)
            return
        if q.startswith("insert into risk_profiles"):
            user_id = int(params[0])
            self.storage[user_id] = tuple(params)
            return
        raise AssertionError(f"Unexpected query: {query}")

    def fetchone(self):
        return self._result


class FakePgConnection:
    def __init__(self):
        self.storage = {}
        self.commits = 0

    def cursor(self):
        return FakePgCursor(self.storage)

    def commit(self):
        self.commits += 1


def test_get_or_create_default_and_persist(tmp_path):
    store_file = tmp_path / "risk_profiles.json"

    store = RiskProfileStore(file_path=str(store_file))
    profile = store.get_or_create_default(123)
    assert profile.user_id == 123
    assert profile.budget_usdt == 1000.0
    assert profile.risk_per_trade_pct == 1.0

    profile.budget_usdt = 2500.0
    profile.risk_per_trade_pct = 1.5
    store.upsert(profile)

    reloaded = RiskProfileStore(file_path=str(store_file))
    saved = reloaded.get(123)
    assert saved is not None
    assert saved.budget_usdt == 2500.0
    assert saved.risk_per_trade_pct == 1.5


def test_profile_validation_ranges():
    profile = RiskProfile(user_id=1, budget_usdt=-10)
    try:
        profile.validate()
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "budget_usdt" in str(exc)

    profile = RiskProfile(user_id=1, budget_usdt=1000, risk_per_trade_pct=10)
    try:
        profile.validate()
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "risk_per_trade_pct" in str(exc)


def test_store_skips_invalid_records_on_load(tmp_path):
    store_file = tmp_path / "risk_profiles.json"
    store_file.write_text(
        """
{
  "profiles": [
    {"user_id": 10, "budget_usdt": 500, "risk_per_trade_pct": 1.0, "max_open_positions": 2, "daily_risk_limit_pct": 4.0},
    {"user_id": 11, "budget_usdt": -1, "risk_per_trade_pct": 1.0, "max_open_positions": 2, "daily_risk_limit_pct": 4.0}
  ]
}
""".strip(),
        encoding="utf-8",
    )

    store = RiskProfileStore(file_path=str(store_file))
    assert store.get(10) is not None
    assert store.get(11) is None


def test_profile_validation_rejects_non_finite_values():
    profile = RiskProfile(user_id=1, budget_usdt=math.nan)
    try:
        profile.validate()
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "finite" in str(exc)


def test_profile_validation_rejects_non_positive_default_leverage():
    profile = RiskProfile(user_id=1, budget_usdt=1000, risk_per_trade_pct=1.0, default_leverage=0)
    try:
        profile.validate()
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "default_leverage" in str(exc)


def test_postgres_backend_upsert_and_get():
    fake_conn = FakePgConnection()

    store = RiskProfileStore(
        backend="postgres",
        postgres_dsn="postgresql://user:pass@localhost/db",
        pg_conn_factory=lambda dsn: fake_conn,
    )

    profile = store.get_or_create_default(42)
    assert profile.user_id == 42

    profile.budget_usdt = 2200.0
    profile.risk_per_trade_pct = 1.7
    store.upsert(profile)

    saved = store.get(42)
    assert saved is not None
    assert saved.budget_usdt == 2200.0
    assert saved.risk_per_trade_pct == 1.7
    assert fake_conn.commits >= 2


def test_postgres_backend_requires_dsn():
    try:
        RiskProfileStore(backend="postgres", postgres_dsn="")
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "postgres_dsn" in str(exc)


def test_backend_validation_rejects_unknown_backend():
    try:
        RiskProfileStore(backend="memory")
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "backend" in str(exc)
