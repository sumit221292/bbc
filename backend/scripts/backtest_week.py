"""Backtest every registered strategy over the last 7 days on BTCUSDT 1h.

Rules (industry-standard retail-style):
  - Starting capital: $1000
  - Position sizing: risk a fixed percentage of *current* capital on every trade
    (compounding). Default 2%. Position size = (capital * risk_pct) / stop_distance.
  - Only one open trade at a time -- new signals while a trade is open are skipped.
  - A trade closes the moment a bar's high/low touches the stop or target.
    If both are touched in the same bar we conservatively assume the stop hit first.
  - Open trades at the end of the test window are marked-to-market on the last close.
  - No fees / slippage modelled (paper trading) -- real performance would be lower.

Run from the backend directory:
    .venv/Scripts/python.exe scripts/backtest_week.py
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

# Windows console defaults to cp1252 — strategy names contain unicode (★).
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# Allow `python scripts/backtest_week.py` from the backend root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.binance import fetch_klines
from app.schemas import Candle, Signal
from app.strategies import list_strategies


SYMBOL = "BTCUSDT"
INTERVAL = "1h"
WARMUP_BARS = 250          # enough for EMA200 + 20-bar lookback
WEEK_BARS = 30 * 24        # 720 hourly bars = 30 days
TOTAL_BARS = WARMUP_BARS + WEEK_BARS  # 970, under Binance 1000 cap
START_CAPITAL = 1000.0
RISK_PCT = 0.02            # 2% of current capital per trade


def _t(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%m-%d %H:%M")


def simulate(
    candles: list[Candle],
    signals: list[Signal],
    week_start_idx: int,
    capital: float = START_CAPITAL,
    risk_pct: float = RISK_PCT,
) -> dict:
    sigs_by_time = {
        s.time: s for s in signals
        if s.entry is not None and s.stop_loss is not None and s.target is not None
    }

    cap = capital
    equity_high = capital
    max_dd = 0.0
    trades: list[dict] = []
    open_trade: dict | None = None

    for i in range(week_start_idx, len(candles)):
        c = candles[i]

        # 1. Check if the open trade exits during this bar.
        if open_trade is not None:
            exit_price = None
            outcome = None
            if open_trade["type"] == "BUY":
                if c.low <= open_trade["stop"]:
                    exit_price, outcome = open_trade["stop"], "LOSS"
                elif c.high >= open_trade["target"]:
                    exit_price, outcome = open_trade["target"], "WIN"
            else:  # SELL
                if c.high >= open_trade["stop"]:
                    exit_price, outcome = open_trade["stop"], "LOSS"
                elif c.low <= open_trade["target"]:
                    exit_price, outcome = open_trade["target"], "WIN"

            if exit_price is not None:
                if open_trade["type"] == "BUY":
                    pnl = (exit_price - open_trade["entry"]) * open_trade["size"]
                else:
                    pnl = (open_trade["entry"] - exit_price) * open_trade["size"]
                cap += pnl
                trades.append({
                    "type": open_trade["type"],
                    "entry_time": open_trade["entered_at"],
                    "entry": open_trade["entry"],
                    "exit_time": c.time,
                    "exit": exit_price,
                    "outcome": outcome,
                    "pnl": pnl,
                    "pnl_pct": pnl / open_trade["cap_at_entry"] * 100.0,
                    "cap_after": cap,
                })
                open_trade = None
                if cap > equity_high:
                    equity_high = cap
                else:
                    dd = (equity_high - cap) / equity_high * 100.0
                    max_dd = max(max_dd, dd)

        # 2. If no trade is open, check if a signal fires at this bar.
        sig = sigs_by_time.get(c.time)
        if sig is not None and open_trade is None:
            stop_dist = abs(sig.entry - sig.stop_loss)
            if stop_dist <= 0:
                continue
            size = (cap * risk_pct) / stop_dist
            open_trade = {
                "type": sig.type,
                "entry": sig.entry,
                "stop": sig.stop_loss,
                "target": sig.target,
                "size": size,
                "entered_at": c.time,
                "cap_at_entry": cap,
            }

    # 3. Mark-to-market any open trade at the final close.
    if open_trade is not None:
        last = candles[-1]
        if open_trade["type"] == "BUY":
            pnl = (last.close - open_trade["entry"]) * open_trade["size"]
        else:
            pnl = (open_trade["entry"] - last.close) * open_trade["size"]
        cap += pnl
        trades.append({
            "type": open_trade["type"],
            "entry_time": open_trade["entered_at"],
            "entry": open_trade["entry"],
            "exit_time": last.time,
            "exit": last.close,
            "outcome": "OPEN",
            "pnl": pnl,
            "pnl_pct": pnl / open_trade["cap_at_entry"] * 100.0,
            "cap_after": cap,
        })

    wins = sum(1 for t in trades if t["outcome"] == "WIN")
    losses = sum(1 for t in trades if t["outcome"] == "LOSS")
    open_count = sum(1 for t in trades if t["outcome"] == "OPEN")
    closed = wins + losses
    return {
        "trades": trades,
        "capital_start": capital,
        "capital_end": cap,
        "total_pnl": cap - capital,
        "total_pnl_pct": (cap - capital) / capital * 100.0,
        "count": len(trades),
        "wins": wins,
        "losses": losses,
        "open": open_count,
        "win_rate": (wins / closed * 100.0) if closed else 0.0,
        "max_dd_pct": max_dd,
    }


async def main() -> None:
    print(f"\n{'=' * 90}")
    print(f"  BACKTEST   {SYMBOL}  |  {INTERVAL}  |  last {WEEK_BARS // 24} days")
    print(f"  Capital ${START_CAPITAL:.0f}   Risk per trade {RISK_PCT * 100:.0f}%   "
          f"One open trade at a time   No fees/slippage modelled")
    print(f"{'=' * 90}\n")

    candles = await fetch_klines(SYMBOL, INTERVAL, TOTAL_BARS)
    week_start_idx = max(0, len(candles) - WEEK_BARS)
    print(f"Window: {_t(candles[week_start_idx].time)}  ->  {_t(candles[-1].time)}  UTC")
    print(f"Bars:   {len(candles)} fetched  ({week_start_idx} warmup, "
          f"{len(candles) - week_start_idx} test bars)\n")

    results: list[tuple[str, str, dict]] = []
    for cls in list_strategies():
        strat = cls()
        signals = strat.evaluate(candles)
        result = simulate(candles, signals, week_start_idx)
        results.append((cls.id, cls.name, result))

    # Per-strategy summary table
    name_w = max(len(name) for _, name, _ in results)
    header = (
        f"{'Strategy':<{name_w}}   "
        f"{'Trades':>6} {'W':>3} {'L':>3} {'O':>3}   "
        f"{'Win %':>6}  {'PnL $':>9}  {'PnL %':>7}  {'MaxDD %':>8}  {'End $':>9}"
    )
    print(header)
    print("-" * len(header))
    for _, name, r in results:
        print(
            f"{name:<{name_w}}   "
            f"{r['count']:>6} {r['wins']:>3} {r['losses']:>3} {r['open']:>3}   "
            f"{r['win_rate']:>5.1f}%  ${r['total_pnl']:>+7.2f}  {r['total_pnl_pct']:>+6.2f}%  "
            f"{r['max_dd_pct']:>7.2f}%  ${r['capital_end']:>7.2f}"
        )

    # Per-strategy trade detail
    print(f"\n\n  TRADE-BY-TRADE DETAIL\n")
    for _, name, r in results:
        print(f"\n-- {name} --")
        if not r["trades"]:
            print("    (no trades -- strategy did not fire in this 7-day window)")
            continue
        for t in r["trades"]:
            print(
                f"    {t['type']:4}  {_t(t['entry_time'])}  ->  {_t(t['exit_time'])}   "
                f"entry ${t['entry']:>9.2f}   exit ${t['exit']:>9.2f}   "
                f"{t['outcome']:5}   PnL ${t['pnl']:>+7.2f} ({t['pnl_pct']:>+5.2f}%)   "
                f"capital ${t['cap_after']:>8.2f}"
            )

    print()


if __name__ == "__main__":
    asyncio.run(main())
