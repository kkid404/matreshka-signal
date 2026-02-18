"""Output formatting for signal cards — console, JSON, CSV."""

from __future__ import annotations

import csv
import json
import os
from typing import List

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from core.models import SignalCard

console = Console()


def print_signal_card(card: SignalCard) -> None:
    dir_color = "green" if card.direction.value == "LONG" else "red"
    sample_note = " ⚠ low sample" if card.low_sample else ""

    body = (
        f"[bold]{card.symbol}[/bold]  "
        f"[{dir_color} bold]{card.direction.value}[/{dir_color} bold]\n"
        f"Timeframe : {card.timeframe}\n"
        f"Signal    : {card.signal_candle_time.strftime('%Y-%m-%d %H:%M UTC')}\n"
        f"Level     : {card.level_price}\n"
        f"Entry     : {card.entry_price}\n"
        f"Stop-Loss : {card.stop_loss}\n"
        f"Take-Profit: {card.take_profit}  (RR {card.rr_target})\n"
        f"Probability: {card.probability_percent:.1f}%  "
        f"(N={card.sample_size_n}{sample_note})\n"
        f"TV Link   : {card.tradingview_link}"
    )

    if card.entry_min_price > 0 and card.entry_max_price > 0:
        body += f"\nEntry Zone: {card.entry_min_price:.6g} - {card.entry_max_price:.6g}"

    if card.ladder:
        body += "\nLadder:"
        for step in card.ladder:
            body += f"\n  TP {step.tp_rr}R — close {step.close_pct*100:.0f}%"
            if step.move_sl_to_be:
                body += " (move SL to BE)"

    console.print(Panel(body, title="Signal", border_style=dir_color))


def print_signals_table(cards: List[SignalCard]) -> None:
    if not cards:
        console.print("[yellow]No signals found.[/yellow]")
        return

    table = Table(title="Matryoshka Signals", show_lines=True)
    table.add_column("Symbol", style="bold")
    table.add_column("Dir")
    table.add_column("Entry", justify="right")
    table.add_column("SL", justify="right")
    table.add_column("TP", justify="right")
    table.add_column("RR", justify="right")
    table.add_column("Prob%", justify="right")
    table.add_column("N", justify="right")
    table.add_column("Signal Time")

    for c in cards:
        dir_style = "green" if c.direction.value == "LONG" else "red"
        table.add_row(
            c.symbol,
            Text(c.direction.value, style=dir_style),
            f"{c.entry_price:.4f}",
            f"{c.stop_loss:.4f}",
            f"{c.take_profit:.4f}",
            f"{c.rr_target}",
            f"{c.probability_percent:.1f}",
            str(c.sample_size_n),
            c.signal_candle_time.strftime("%Y-%m-%d %H:%M"),
        )
    console.print(table)


def save_signals_json(cards: List[SignalCard], path: str) -> None:
    data = [c.to_dict() for c in cards]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    console.print(f"[dim]Saved {len(cards)} signal(s) to {path}[/dim]")


_CSV_FIELDS = [
    "symbol", "direction", "timeframe", "signal_candle_time",
    "level_price", "entry_price", "entry_min_price", "entry_max_price", "stop_loss", "take_profit",
    "rr_target", "probability_percent", "sample_size_N",
    "tradingview_link",
]


def save_signals_csv(cards: List[SignalCard], path: str) -> None:
    rows = [c.to_dict() for c in cards]
    file_exists = os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)
    console.print(f"[dim]Appended {len(cards)} signal(s) to {path}[/dim]")
