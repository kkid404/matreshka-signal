from __future__ import annotations

import logging
from typing import Dict, List

from core.config import ScannerConfig
from core.data_fetcher import DataFetcher
from core.levels import cluster_levels, detect_swing_highs_lows, get_manual_levels
from core.models import SignalCard
from core.probability import calculate_probability
from strategies.base import BaseStrategy

logger = logging.getLogger("matryoshka")


def replay_symbol_history(
    cfg: ScannerConfig,
    fetcher: DataFetcher,
    symbol: str,
    strategies: List[BaseStrategy],
    lookback_h4: int,
) -> List[SignalCard]:
    """Replay historical candles for one symbol and keep the latest signal per strategy."""
    h4_limit = max(lookback_h4, cfg.setup.lookback_bars, 200)
    # Roughly 6 H4 candles per day + margin for EMA warm-up
    d1_limit = max(cfg.context.lookback_bars, h4_limit // 6 + cfg.context.ema_period + 50)

    d1_candles = fetcher.fetch_candles(symbol, cfg.context.timeframe, limit=d1_limit)
    h4_candles = fetcher.fetch_candles(symbol, cfg.setup.timeframe, limit=h4_limit)

    if d1_candles and h4_candles:
        logger.info(
            "Replay data window %s: D1=%d (%s .. %s), H4=%d (%s .. %s)",
            symbol,
            len(d1_candles),
            d1_candles[0].timestamp.isoformat(),
            d1_candles[-1].timestamp.isoformat(),
            len(h4_candles),
            h4_candles[0].timestamp.isoformat(),
            h4_candles[-1].timestamp.isoformat(),
        )

    if len(h4_candles) < 40:
        logger.warning("%s: not enough H4 data for replay (%d candles)", symbol, len(h4_candles))
        return []

    start = max(30, len(h4_candles) - lookback_h4)
    latest_by_strategy: Dict[str, SignalCard] = {}
    hit_counts: Dict[str, int] = {s.name: 0 for s in strategies}
    d1_short_slices = 0
    min_d1_slice = 10**9
    max_d1_slice = 0

    # Strategy.scan() uses h4[-2] as last closed candle.
    for end in range(start + 2, len(h4_candles) + 1):
        h4_slice = h4_candles[:end]
        signal_ts = h4_slice[-2].timestamp
        d1_slice = [c for c in d1_candles if c.timestamp <= signal_ts]
        d1_len = len(d1_slice)
        min_d1_slice = min(min_d1_slice, d1_len)
        max_d1_slice = max(max_d1_slice, d1_len)
        if d1_len < cfg.context.ema_period:
            d1_short_slices += 1
        for strat in strategies:
            try:
                card = strat.scan(symbol, d1_slice, h4_slice, cfg)
            except Exception:
                logger.exception("%s [%s]: strategy crashed during replay", symbol, strat.name)
                continue
            if card is None:
                continue
            latest_by_strategy[strat.name] = card
            hit_counts[strat.name] += 1

    # Preserve configured strategy order
    cards = [latest_by_strategy[s.name] for s in strategies if s.name in latest_by_strategy]

    # Optional probability only for Matryoshka (same behavior as regular scan)
    for card in cards:
        if card.strategy_name == "matryoshka":
            levels = _get_levels(symbol, h4_candles, cfg)
            prob = calculate_probability(symbol, h4_candles, d1_candles, levels, cfg)
            card.probability_percent = prob.probability_pct
            card.sample_size_n = prob.total
            card.low_sample = prob.low_sample

    logger.info(
        "Replay D1 slice stats %s: min=%d max=%d below_ema_period=%d/%d",
        symbol,
        min_d1_slice if min_d1_slice != 10**9 else 0,
        max_d1_slice,
        d1_short_slices,
        max(1, len(h4_candles) - (start + 1)),
    )
    logger.info("Replay matches by strategy: %s", hit_counts)

    return cards


def _get_levels(symbol: str, h4_candles, cfg: ScannerConfig) -> List[float]:
    if cfg.levels_mode == "manual":
        return get_manual_levels(cfg.levels_manual, symbol)
    raw = detect_swing_highs_lows(h4_candles, order=5)
    return cluster_levels(raw, tolerance_pct=0.5)
