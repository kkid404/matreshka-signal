"""Tests for acceptable entry price range in SignalCard."""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.models import Direction, SignalCard


def _base_card(direction: Direction, entry: float, stop_loss: float) -> SignalCard:
    return SignalCard(
        symbol="BTCUSDT",
        direction=direction,
        timeframe="H4",
        signal_candle_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
        level_price=100.0,
        entry_price=entry,
        stop_loss=stop_loss,
        take_profit=120.0,
        rr_target=3.0,
        probability_percent=50.0,
        sample_size_n=100,
    )


def test_entry_range_auto_for_long():
    card = _base_card(Direction.LONG, entry=100.0, stop_loss=96.0)
    # risk=4, zone=1 => [99,100]
    assert card.entry_min_price == 99.0
    assert card.entry_max_price == 100.0


def test_entry_range_auto_for_short():
    card = _base_card(Direction.SHORT, entry=100.0, stop_loss=104.0)
    # risk=4, zone=1 => [100,101]
    assert card.entry_min_price == 100.0
    assert card.entry_max_price == 101.0


def test_entry_range_keeps_manual_values_and_swaps_if_needed():
    card = SignalCard(
        symbol="BTCUSDT",
        direction=Direction.LONG,
        timeframe="H4",
        signal_candle_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
        level_price=100.0,
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=115.0,
        rr_target=3.0,
        probability_percent=50.0,
        sample_size_n=100,
        entry_min_price=101.0,
        entry_max_price=99.0,
    )

    assert card.entry_min_price == 99.0
    assert card.entry_max_price == 101.0


def test_entry_range_present_in_payload_dict():
    card = _base_card(Direction.LONG, entry=100.0, stop_loss=96.0)
    payload = card.to_dict()
    assert "entry_min_price" in payload
    assert "entry_max_price" in payload
