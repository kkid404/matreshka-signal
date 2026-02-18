"""Trader risk profile model and file-backed store for Telegram users."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import os
from typing import Any, Dict, Optional

try:
    import psycopg
except ImportError:  # pragma: no cover - optional dependency
    psycopg = None


@dataclass
class RiskProfile:
    user_id: int
    budget_usdt: float = 1000.0
    risk_per_trade_pct: float = 1.0
    max_open_positions: int = 1
    daily_risk_limit_pct: float = 4.0
    default_leverage: Optional[int] = None
    is_active: bool = True
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.updated_at:
            self.updated_at = datetime.now(timezone.utc).isoformat()

    def validate(self) -> None:
        if self.user_id <= 0:
            raise ValueError("user_id must be positive")
        if not math.isfinite(self.budget_usdt):
            raise ValueError("budget_usdt must be a finite number")
        if self.budget_usdt <= 0:
            raise ValueError("budget_usdt must be > 0")
        if not math.isfinite(self.risk_per_trade_pct):
            raise ValueError("risk_per_trade_pct must be a finite number")
        if self.risk_per_trade_pct < 0.1 or self.risk_per_trade_pct > 5.0:
            raise ValueError("risk_per_trade_pct must be in range 0.1..5.0")
        if self.max_open_positions < 1 or self.max_open_positions > 20:
            raise ValueError("max_open_positions must be in range 1..20")
        if not math.isfinite(self.daily_risk_limit_pct):
            raise ValueError("daily_risk_limit_pct must be a finite number")
        if self.daily_risk_limit_pct < 0.1 or self.daily_risk_limit_pct > 20.0:
            raise ValueError("daily_risk_limit_pct must be in range 0.1..20.0")
        if self.default_leverage is not None and self.default_leverage <= 0:
            raise ValueError("default_leverage must be > 0")

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, object]:
        return {
            "user_id": self.user_id,
            "budget_usdt": self.budget_usdt,
            "risk_per_trade_pct": self.risk_per_trade_pct,
            "max_open_positions": self.max_open_positions,
            "daily_risk_limit_pct": self.daily_risk_limit_pct,
            "default_leverage": self.default_leverage,
            "is_active": self.is_active,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, object]) -> "RiskProfile":
        return cls(
            user_id=int(payload.get("user_id", 0) or 0),
            budget_usdt=float(payload.get("budget_usdt", 1000.0) or 1000.0),
            risk_per_trade_pct=float(payload.get("risk_per_trade_pct", 1.0) or 1.0),
            max_open_positions=int(payload.get("max_open_positions", 1) or 1),
            daily_risk_limit_pct=float(payload.get("daily_risk_limit_pct", 4.0) or 4.0),
            default_leverage=(
                int(payload["default_leverage"])
                if payload.get("default_leverage") is not None
                else None
            ),
            is_active=bool(payload.get("is_active", True)),
            updated_at=str(payload.get("updated_at", "") or ""),
        )

    @classmethod
    def default_for_user(cls, user_id: int) -> "RiskProfile":
        return cls(user_id=user_id)


class RiskProfileStore:
    """Storage keyed by Telegram user_id (file or PostgreSQL backend)."""

    def __init__(
        self,
        file_path: str = "data/risk_profiles.json",
        backend: str = "file",
        postgres_dsn: str = "",
        pg_conn_factory: Any = None,
    ):
        self._file_path = file_path
        self._backend = (backend or "file").lower()
        self._postgres_dsn = postgres_dsn
        self._pg_conn_factory = pg_conn_factory
        self._conn = None
        self._profiles: Dict[int, RiskProfile] = {}

        if self._backend == "file":
            self._load()
        elif self._backend == "postgres":
            self._init_postgres()
        else:
            raise ValueError("backend must be one of: file, postgres")

    def get(self, user_id: int) -> Optional[RiskProfile]:
        if self._backend == "postgres":
            row = self._fetch_postgres_row(user_id)
            if row is None:
                return None
            return self._profile_from_postgres_row(row)
        return self._profiles.get(user_id)

    def get_or_create_default(self, user_id: int) -> RiskProfile:
        profile = self.get(user_id)
        if profile is not None:
            return profile
        profile = RiskProfile.default_for_user(user_id)
        self.upsert(profile)
        return profile

    def upsert(self, profile: RiskProfile) -> RiskProfile:
        profile.validate()
        profile.touch()

        if self._backend == "postgres":
            self._upsert_postgres(profile)
            return profile

        self._profiles[profile.user_id] = profile
        self._save()
        return profile

    def _init_postgres(self) -> None:
        if not self._postgres_dsn:
            raise ValueError("postgres_dsn is required for backend=postgres")

        if self._pg_conn_factory is not None:
            self._conn = self._pg_conn_factory(self._postgres_dsn)
        else:
            if psycopg is None:
                raise RuntimeError("psycopg is required for backend=postgres")
            self._conn = psycopg.connect(self._postgres_dsn)

        self._ensure_postgres_schema()

    def _ensure_postgres_schema(self) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS risk_profiles (
                    user_id BIGINT PRIMARY KEY,
                    budget_usdt DOUBLE PRECISION NOT NULL,
                    risk_per_trade_pct DOUBLE PRECISION NOT NULL,
                    max_open_positions INTEGER NOT NULL,
                    daily_risk_limit_pct DOUBLE PRECISION NOT NULL,
                    default_leverage INTEGER NULL,
                    is_active BOOLEAN NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )
        self._commit_if_supported()

    def _fetch_postgres_row(self, user_id: int) -> Optional[tuple]:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    user_id,
                    budget_usdt,
                    risk_per_trade_pct,
                    max_open_positions,
                    daily_risk_limit_pct,
                    default_leverage,
                    is_active,
                    updated_at
                FROM risk_profiles
                WHERE user_id = %s
                """,
                (user_id,),
            )
            return cur.fetchone()

    def _upsert_postgres(self, profile: RiskProfile) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO risk_profiles (
                    user_id,
                    budget_usdt,
                    risk_per_trade_pct,
                    max_open_positions,
                    daily_risk_limit_pct,
                    default_leverage,
                    is_active,
                    updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    budget_usdt = EXCLUDED.budget_usdt,
                    risk_per_trade_pct = EXCLUDED.risk_per_trade_pct,
                    max_open_positions = EXCLUDED.max_open_positions,
                    daily_risk_limit_pct = EXCLUDED.daily_risk_limit_pct,
                    default_leverage = EXCLUDED.default_leverage,
                    is_active = EXCLUDED.is_active,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    profile.user_id,
                    profile.budget_usdt,
                    profile.risk_per_trade_pct,
                    profile.max_open_positions,
                    profile.daily_risk_limit_pct,
                    profile.default_leverage,
                    profile.is_active,
                    profile.updated_at,
                ),
            )
        self._commit_if_supported()

    @staticmethod
    def _profile_from_postgres_row(row: tuple) -> RiskProfile:
        updated_at = row[7]
        updated_at_value = updated_at.isoformat() if hasattr(updated_at, "isoformat") else str(updated_at or "")
        return RiskProfile(
            user_id=int(row[0]),
            budget_usdt=float(row[1]),
            risk_per_trade_pct=float(row[2]),
            max_open_positions=int(row[3]),
            daily_risk_limit_pct=float(row[4]),
            default_leverage=(int(row[5]) if row[5] is not None else None),
            is_active=bool(row[6]),
            updated_at=updated_at_value,
        )

    def _commit_if_supported(self) -> None:
        commit = getattr(self._conn, "commit", None)
        if callable(commit):
            commit()

    def _load(self) -> None:
        if not os.path.exists(self._file_path):
            return
        try:
            with open(self._file_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            records = raw.get("profiles", [])
            for item in records:
                profile = RiskProfile.from_dict(item)
                try:
                    profile.validate()
                except ValueError:
                    continue
                self._profiles[profile.user_id] = profile
        except Exception:
            self._profiles = {}

    def _save(self) -> None:
        directory = os.path.dirname(self._file_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        payload = {"profiles": [p.to_dict() for p in self._profiles.values()]}
        with open(self._file_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
