from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import List

from core.cache import SignalCache
from core.config import ScannerConfig
from core.data_fetcher import DataFetcher
from core.levels import resolve_levels
from core.models import SignalCard
from core.probability import calculate_probability
from strategies.base import BaseStrategy

logger = logging.getLogger("matryoshka")

_SYMBOL_THROTTLE = 0.35


def _timeframe_to_timedelta(timeframe: str) -> timedelta:
    tf = (timeframe or "").strip()
    if len(tf) < 2:
        return timedelta(0)
    unit = tf[-1]
    try:
        value = int(tf[:-1])
    except ValueError:
        return timedelta(0)

    if unit in ("m", "M"):
        return timedelta(minutes=value)
    if unit in ("h", "H"):
        return timedelta(hours=value)
    if unit in ("d", "D"):
        return timedelta(days=value)
    if unit in ("w", "W"):
        return timedelta(weeks=value)
    return timedelta(0)


def _has_invalid_candle_sequence(candles, timeframe: str, max_gap_factor: float) -> bool:
    if len(candles) < 2:
        return False

    expected_step = _timeframe_to_timedelta(timeframe)
    if expected_step <= timedelta(0):
        return False

    max_gap = expected_step * max(max_gap_factor, 1.0)
    prev_ts = candles[0].timestamp
    for candle in candles[1:]:
        if candle.timestamp <= prev_ts:
            return True
        if candle.timestamp - prev_ts > max_gap:
            return True
        prev_ts = candle.timestamp
    return False


def _zero_volume_share(candles) -> float:
    if not candles:
        return 1.0
    zero_count = sum(1 for c in candles if c.volume <= 0)
    return zero_count / len(candles)


def resolve_symbols(cfg: ScannerConfig, fetcher: DataFetcher) -> List[str]:
    """Resolve symbols according to symbols_mode and filters."""
    flt = cfg.symbol_filter

    if cfg.symbols_mode == "manual":
        return cfg.symbols

    if cfg.symbols_mode == "top_n":
        return fetcher.get_top_usdt_perpetuals(
            top_n=cfg.top_n,
            min_volume_24h=flt.min_volume_24h,
            min_open_interest=flt.min_open_interest,
            exclude=flt.exclude,
        )

    return fetcher.get_all_usdt_perpetuals(
        min_volume_24h=flt.min_volume_24h,
        min_open_interest=flt.min_open_interest,
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
            if len(d1_candles) < cfg.validation.min_d1_candles:
                logger.warning(
                    "%s: not enough D1 data (%d candles, need >= %d)",
                    symbol,
                    len(d1_candles),
                    cfg.validation.min_d1_candles,
                )
                continue

            h4_limit = max(cfg.setup.lookback_bars, cfg.probability.lookback_bars)
            h4_candles = fetcher.fetch_candles(symbol, cfg.setup.timeframe, limit=h4_limit)

            if len(h4_candles) < cfg.validation.min_h4_candles:
                logger.warning(
                    "%s: not enough H4 data (%d candles, need >= %d)",
                    symbol,
                    len(h4_candles),
                    cfg.validation.min_h4_candles,
                )
                continue

            if _has_invalid_candle_sequence(
                h4_candles,
                timeframe=cfg.setup.timeframe,
                max_gap_factor=cfg.validation.max_candle_gap_factor,
            ):
                logger.warning(
                    "%s: skipped due to candle gaps/time-order issues on %s",
                    symbol,
                    cfg.setup.timeframe,
                )
                continue

            zero_volume_share = _zero_volume_share(h4_candles)
            if zero_volume_share > cfg.validation.max_zero_volume_share:
                logger.warning(
                    "%s: skipped as illiquid (zero-volume share %.2f > %.2f)",
                    symbol,
                    zero_volume_share,
                    cfg.validation.max_zero_volume_share,
                )
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
    if not h4_candles:
        return []
    ref_idx = -2 if len(h4_candles) >= 2 else -1
    return resolve_levels(
        cfg.levels_manual,
        symbol,
        h4_candles,
        cfg,
        reference_price=h4_candles[ref_idx].close,
    )
