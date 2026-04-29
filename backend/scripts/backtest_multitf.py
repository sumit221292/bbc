"""Multi-timeframe backtest across all 13 strategies with realistic fees.

Each timeframe uses a window long enough to give meaningful sample size:
  - 15m  | 7 days   (672 test bars)
  - 1h   | 30 days  (720 test bars)
  - 4h   | 90 days  (540 test bars)
  - 1d   | 1 year   (365 test bars)

Risk model:
  - $1000 starting capital
  - 2% of current capital risked per trade (compounding)
  - One open trade at a time
  - Binance spot fees: 0.1% taker per side = 0.2% round trip per trade
  - No slippage modelled (would further reduce real returns)

After all runs, prints a "consistency board" — strategies ranked by how many
timeframes they were profitable on. A strategy that only wins in one window is
likely overfit; one that wins in 3+ windows is showing real edge.
"""
from __future__ import annotations

import asyncio
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.binance import fetch_klines
from app.schemas import Candle, Signal
from app.strategies import list_strategies


SYMBOL = "BTCUSDT"
WARMUP_BARS = 250
START_CAPITAL = 1000.0
RISK_PCT = 0.02
FEE_PCT = 0.001  # 0.1% per side, 0.2% round trip

# (interval, days_in_window) — Binance limit is 1000 bars per request, so each is sized to fit.
TIMEFRAMES = [
    ("15m", 7,   96),   # 672 + 250 = 922
    ("1h",  30,  24),   # 720 + 250 = 970
    ("4h",  90,  6),    # 540 + 250 = 790
    ("1d",  365, 1),    # 365 + 250 = 615
]


def _t(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def simulate(candles, signals, week_start_idx, capital=START_CAPITAL,
             risk_pct=RISK_PCT, fee_pct=FEE_PCT):
    sigs_by_time = {
        s.time: s for s in signals
        if s.entry is not None and s.stop_loss is not None and s.target is not None
    }

    cap = capital
    equity_high = capital
    max_dd = 0.0
    trades = []
    open_trade = None

    for i in range(week_start_idx, len(candles)):
        c = candles[i]

        # Exit check
        if open_trade is not None:
            exit_price = None
            outcome = None
            if open_trade["type"] == "BUY":
                if c.low <= open_trade["stop"]:
                    exit_price, outcome = open_trade["stop"], "LOSS"
                elif c.high >= open_trade["target"]:
                    exit_price, outcome = open_trade["target"], "WIN"
            else:
                if c.high >= open_trade["stop"]:
                    exit_price, outcome = open_trade["stop"], "LOSS"
                elif c.low <= open_trade["target"]:
                    exit_price, outcome = open_trade["target"], "WIN"

            if exit_price is not None:
                if open_trade["type"] == "BUY":
                    raw_pnl = (exit_price - open_trade["entry"]) * open_trade["size"]
                else:
                    raw_pnl = (open_trade["entry"] - exit_price) * open_trade["size"]
                # Round-trip fees on notional value at entry & exit
                fee_in = open_trade["entry"] * open_trade["size"] * fee_pct
                fee_out = exit_price * open_trade["size"] * fee_pct
                pnl = raw_pnl - fee_in - fee_out
                cap += pnl
                trades.append({
                    "type": open_trade["type"], "entry": open_trade["entry"],
                    "exit": exit_price, "outcome": outcome, "pnl": pnl,
                    "cap_after": cap,
                })
                open_trade = None
                if cap > equity_high:
                    equity_high = cap
                else:
                    dd = (equity_high - cap) / equity_high * 100.0
                    max_dd = max(max_dd, dd)

        # Entry check
        sig = sigs_by_time.get(c.time)
        if sig is not None and open_trade is None:
            stop_dist = abs(sig.entry - sig.stop_loss)
            if stop_dist <= 0:
                continue
            size = (cap * risk_pct) / stop_dist
            open_trade = {
                "type": sig.type, "entry": sig.entry,
                "stop": sig.stop_loss, "target": sig.target,
                "size": size, "cap_at_entry": cap,
            }

    # Mark to market
    if open_trade is not None:
        last = candles[-1]
        if open_trade["type"] == "BUY":
            raw_pnl = (last.close - open_trade["entry"]) * open_trade["size"]
        else:
            raw_pnl = (open_trade["entry"] - last.close) * open_trade["size"]
        fee_in = open_trade["entry"] * open_trade["size"] * fee_pct
        fee_out = last.close * open_trade["size"] * fee_pct
        pnl = raw_pnl - fee_in - fee_out
        cap += pnl
        trades.append({
            "type": open_trade["type"], "entry": open_trade["entry"],
            "exit": last.close, "outcome": "OPEN", "pnl": pnl, "cap_after": cap,
        })

    wins = sum(1 for t in trades if t["outcome"] == "WIN")
    losses = sum(1 for t in trades if t["outcome"] == "LOSS")
    open_count = sum(1 for t in trades if t["outcome"] == "OPEN")
    closed = wins + losses
    return {
        "capital_end": cap,
        "total_pnl_pct": (cap - capital) / capital * 100.0,
        "count": len(trades),
        "wins": wins, "losses": losses, "open": open_count,
        "win_rate": (wins / closed * 100.0) if closed else 0.0,
        "max_dd_pct": max_dd,
    }


async def run_timeframe(interval: str, days: int, bars_per_day: int):
    test_bars = days * bars_per_day
    total = WARMUP_BARS + test_bars
    candles = await fetch_klines(SYMBOL, interval, total)
    week_start_idx = max(0, len(candles) - test_bars)

    print(f"\n{'=' * 100}")
    print(f"  {interval:>4}  |  last {days:>3} days  |  {_t(candles[week_start_idx].time)} -> {_t(candles[-1].time)}  "
          f"({test_bars} test bars, {len(candles)} fetched)")
    print(f"{'=' * 100}")

    rows = []
    for cls in list_strategies():
        signals = cls().evaluate(candles)
        r = simulate(candles, signals, week_start_idx)
        rows.append((cls.name, r))

    # Sort by PnL descending for this timeframe
    rows.sort(key=lambda x: x[1]["total_pnl_pct"], reverse=True)
    name_w = max(len(n) for n, _ in rows)
    print(f"{'Strategy':<{name_w}}   {'Trades':>6} {'W':>3} {'L':>3} {'O':>3}   "
          f"{'Win %':>6}  {'PnL %':>8}  {'MaxDD %':>8}  {'End $':>9}")
    print("-" * (name_w + 64))
    for name, r in rows:
        marker = " *" if r["total_pnl_pct"] > 0 else "  "
        print(f"{name:<{name_w}}{marker} {r['count']:>6} {r['wins']:>3} {r['losses']:>3} {r['open']:>3}   "
              f"{r['win_rate']:>5.1f}%  {r['total_pnl_pct']:>+7.2f}%  {r['max_dd_pct']:>7.2f}%  "
              f"${r['capital_end']:>7.2f}")
    return rows


async def main():
    print(f"\n  MULTI-TIMEFRAME BACKTEST  |  {SYMBOL}  |  Capital ${START_CAPITAL:.0f}  "
          f"|  Risk {RISK_PCT*100:.0f}%/trade  |  Fees {FEE_PCT*100:.1f}% per side ({FEE_PCT*200:.1f}% round-trip)")

    all_results = {}  # interval -> [(name, result)]
    for interval, days, bpd in TIMEFRAMES:
        all_results[interval] = await run_timeframe(interval, days, bpd)

    # Consistency board
    print(f"\n\n{'=' * 100}")
    print(f"  CONSISTENCY BOARD  -- a strategy is robust if it's profitable across multiple timeframes")
    print(f"{'=' * 100}\n")

    by_strategy = defaultdict(dict)  # name -> {interval: pnl_pct}
    for interval, rows in all_results.items():
        for name, r in rows:
            by_strategy[name][interval] = r["total_pnl_pct"]

    intervals = [tf[0] for tf in TIMEFRAMES]
    name_w = max(len(n) for n in by_strategy)
    header = f"{'Strategy':<{name_w}}   " + "  ".join(f"{tf:>8}" for tf in intervals) + "   " + f"{'Profitable on':>14}   {'Avg PnL %':>10}"
    print(header)
    print("-" * len(header))

    rankings = []
    for name, results in by_strategy.items():
        positive_count = sum(1 for v in results.values() if v > 0)
        avg = sum(results.values()) / len(results)
        rankings.append((name, results, positive_count, avg))

    # Sort: most timeframes profitable, then highest avg
    rankings.sort(key=lambda x: (-x[2], -x[3]))

    for name, results, positive_count, avg in rankings:
        cells = "  ".join(f"{results.get(tf, 0):>+7.2f}%" for tf in intervals)
        marker = "***" if positive_count >= 3 else " ** " if positive_count == 2 else "  *" if positive_count == 1 else "   "
        print(f"{name:<{name_w}}   {cells}   {positive_count}/4 {marker:<3}   {avg:>+8.2f}%")

    print(f"\n*** = profitable on 3+ timeframes (robust)   ** = 2   * = 1   none = lost on all")
    print(f"Note: All numbers include 0.2% round-trip Binance spot fees.\n")


if __name__ == "__main__":
    asyncio.run(main())
