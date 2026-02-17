"""Configuration for the Matryoshka scanner."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Literal

from core.models import LadderStep


@dataclass
class SymbolFilter:
    min_volume_24h: float = 10_000_000
    min_open_interest: float = 0.0
    exclude: List[str] = field(default_factory=lambda: [
        "USDCUSDT", "DAIUSDT", "TUSDUSDT", "BUSDUSDT",
    ])


@dataclass
class ContextConfig:
    ema_period: int = 50
    timeframe: str = "1d"
    lookback_bars: int = 200


@dataclass
class TouchConfig:
    mode: Literal["range_touch", "tolerance_touch"] = "range_touch"
    tolerance_value: float = 0.3
    tolerance_unit: Literal["percent", "atr"] = "percent"


@dataclass
class TriggerConfig:
    wick_measure_mode: Literal["wick_vs_body", "wick_vs_range"] = "wick_vs_body"
    min_wick_ratio: float = 1.5
    min_body_size: float = 0.0001
    close_position_k: float = 0.5


@dataclass
class StopLossConfig:
    mode: Literal["signal_wick_extreme"] = "signal_wick_extreme"
    buffer_mode: Literal["fixed", "percent", "atr"] = "percent"
    buffer_value: float = 0.1


@dataclass
class TakeProfitConfig:
    rr_target: float = 3.0
    ladder_enabled: bool = False
    ladder_steps: List[LadderStep] = field(default_factory=list)


@dataclass
class ValidationConfig:
    min_sl_distance_pct: float = 0.05
    max_sl_distance_pct: float = 10.0


@dataclass
class ProbabilityConfig:
    lookback_bars: int = 2000
    max_bars_to_resolve: int = 50
    min_sample_size: int = 30
    unresolved_counts_as: float = 0.5


@dataclass
class SetupConfig:
    timeframe: str = "4h"
    lookback_bars: int = 1000


@dataclass
class TelegramConfig:
    enabled: bool = False
    bot_token: str = ""
    chat_id: str = ""


@dataclass
class ScannerConfig:
    symbols_mode: Literal["all", "top_n", "manual"] = "all"
    top_n: int = 100
    symbols: List[str] = field(default_factory=lambda: ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    symbol_filter: SymbolFilter = field(default_factory=SymbolFilter)

    context: ContextConfig = field(default_factory=ContextConfig)
    setup: SetupConfig = field(default_factory=SetupConfig)
    touch: TouchConfig = field(default_factory=TouchConfig)
    trigger: TriggerConfig = field(default_factory=TriggerConfig)
    stop_loss: StopLossConfig = field(default_factory=StopLossConfig)
    take_profit: TakeProfitConfig = field(default_factory=TakeProfitConfig)
    validation: ValidationConfig = field(default_factory=ValidationConfig)
    probability: ProbabilityConfig = field(default_factory=ProbabilityConfig)

    levels_mode: Literal["manual", "auto"] = "auto"
    levels_manual: Dict[str, List[float]] = field(default_factory=lambda: {
        "BTCUSDT": [43000, 41650],
        "SOLUSDT": [90, 85],
    })

    enabled_strategies: List[str] = field(default_factory=lambda: [
        "matryoshka", "ema_bounce", "breakout", "engulfing", "momentum_break", "ema_cross",
    ])

    telegram: TelegramConfig = field(default_factory=TelegramConfig)

    scan_interval_seconds: int = 900
    output_json: str = "signals.json"
    output_csv: str = "signals.csv"
