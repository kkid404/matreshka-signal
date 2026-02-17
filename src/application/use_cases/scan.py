from __future__ import annotations

import logging
import time
from typing import List

from core.cache import SignalCache
from core.config import ScannerConfig
from core.data_fetcher import DataFetcher
from core.levels import cluster_levels, detect_swing_highs_lows, get_manual_levels
from core.models import SignalCard
from core.probability import calculate_probability
from strategies.base import BaseStrategy

logger = logging.getLogger("matryoshka")

_SYMBOL_THROTTLE = 0.35


def resolve_symbols(cfg: ScannerConfig, fetcher: DataFetcher) -> List[str]:
    """Resolve symbols according to symbols_mode and filters."""
    flt = cfg.symbol_filter

    if cfg.symbols_mode == "manual":
        return cfg.symbols

    if cfg.symbols_mode == "top_n":
        return fetcher.get_top_usdt_perpetuals(
            top_n=cfg.top_n,
            min_volume_24h=flt.min_volume_24h,
            exclude=flt.exclude,
        )

    return fetcher.get_all_usdt_perpetuals(
        min_volume_24h=flt.min_volume_24h,
        exclude=flt.exclude,
    )


def run_scan(
    cfg: ScannerConfig,
    fetcher: DataFetcher,
    cache: SignalCache,
    symbols: List[str],
    strategies: List[BaseStrategy],
) -> List[SignalCard]:
    """Execute one full scan across all configured symbols x strategies."""
    signals: List[SignalCard] = []
    total = len(symbols)

    for i, symbol in enumerate(symbols, 1):
        if i % 50 == 0 or i == 1:
            logger.info("Progress: %d/%d symbols ...", i, total)
        logger.debug("Scanning %s ...", symbol)
        try:
            d1_candles = fetcher.fetch_candles(symbol, cfg.context.timeframe, limit=cfg.context.lookback_bars)

            h4_limit = max(cfg.setup.lookback_bars, cfg.probability.lookback_bars)
            h4_candles = fetcher.fetch_candles(symbol, cfg.setup.timeframe, limit=h4_limit)

            if len(h4_candles) < 30:
                logger.warning("%s: not enough H4 data (%d candles)", symbol, len(h4_candles))
                continue

            found_any = False
            for strat in strategies:
                try:
                    card = strat.scan(symbol, d1_candles, h4_candles, cfg)
                except Exception:
                    logger.exception("%s [%s]: strategy crashed", symbol, strat.name)
                    continue
                if card is None:
                    continue

                sig_time_iso = card.signal_candle_time.isoformat()
                cache_key = f"{card.strategy_name}:{card.direction.value}"
                if not cache.is_new(symbol, sig_time_iso, cache_key):
                    logger.debug("%s [%s]: signal already emitted", symbol, strat.name)
                    continue

                if strat.name == "matryoshka":
                    levels = _get_levels(symbol, h4_candles, cfg)
                    prob = calculate_probability(symbol, h4_candles, d1_candles, levels, cfg)
                    card.probability_percent = prob.probability_pct
                    card.sample_size_n = prob.total
                    card.low_sample = prob.low_sample

                signals.append(card)
                cache.mark(symbol, sig_time_iso, cache_key)
                found_any = True

            if not found_any:
                logger.debug("%s: no signal from any strategy", symbol)

        except Exception:
            logger.exception("Error scanning %s", symbol)

        time.sleep(_SYMBOL_THROTTLE)

    return signals


def _get_levels(symbol: str, h4_candles, cfg: ScannerConfig) -> List[float]:
    if cfg.levels_mode == "manual":
        return get_manual_levels(cfg.levels_manual, symbol)
    raw = detect_swing_highs_lows(h4_candles, order=5)
    return cluster_levels(raw, tolerance_pct=0.5)
