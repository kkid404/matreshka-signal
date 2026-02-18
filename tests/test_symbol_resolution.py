"""Unit tests for symbol resolution filters."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from application.use_cases.scan import resolve_symbols
from core.config import ScannerConfig


class FakeFetcher:
    def __init__(self):
        self.last_top_call = None
        self.last_all_call = None

    def get_top_usdt_perpetuals(self, top_n=50, min_volume_24h=0.0, min_open_interest=0.0, exclude=None):
        self.last_top_call = {
            "top_n": top_n,
            "min_volume_24h": min_volume_24h,
            "min_open_interest": min_open_interest,
            "exclude": exclude,
        }
        return ["BTCUSDT", "ETHUSDT"]

    def get_all_usdt_perpetuals(self, min_volume_24h=0.0, min_open_interest=0.0, exclude=None):
        self.last_all_call = {
            "min_volume_24h": min_volume_24h,
            "min_open_interest": min_open_interest,
            "exclude": exclude,
        }
        return ["SOLUSDT", "XRPUSDT"]


def test_resolve_symbols_top_n_passes_open_interest_filter():
    cfg = ScannerConfig()
    cfg.symbols_mode = "top_n"
    cfg.top_n = 25
    cfg.symbol_filter.min_volume_24h = 123.0
    cfg.symbol_filter.min_open_interest = 456.0
    cfg.symbol_filter.exclude = ["BTCUSDT"]

    fetcher = FakeFetcher()
    symbols = resolve_symbols(cfg, fetcher)

    assert symbols == ["BTCUSDT", "ETHUSDT"]
    assert fetcher.last_top_call == {
        "top_n": 25,
        "min_volume_24h": 123.0,
        "min_open_interest": 456.0,
        "exclude": ["BTCUSDT"],
    }


def test_resolve_symbols_all_passes_open_interest_filter():
    cfg = ScannerConfig()
    cfg.symbols_mode = "all"
    cfg.symbol_filter.min_volume_24h = 111.0
    cfg.symbol_filter.min_open_interest = 222.0
    cfg.symbol_filter.exclude = ["USDCUSDT"]

    fetcher = FakeFetcher()
    symbols = resolve_symbols(cfg, fetcher)

    assert symbols == ["SOLUSDT", "XRPUSDT"]
    assert fetcher.last_all_call == {
        "min_volume_24h": 111.0,
        "min_open_interest": 222.0,
        "exclude": ["USDCUSDT"],
    }
