"""Backtest the multi-timeframe adaptive strategy.

We fetch 1h / 4h / 1d candles in parallel, build an MTF context, then test
three variants on the most recent 30-day window of 1h bars (with proper
warmup). Same risk model as the other backtests:
  - $1000 capital, 2% risk per trade, one trade at a time, 0.2% round-trip fees.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.binance import fetch_klines
from app.multi_tf import (
    MTFContext, evaluate_strict, evaluate_2screen, evaluate_relaxed,
    evaluate_chop_aware, evaluate_chop_only,
)


SYMBOL = "BTCUSDT"
START_CAPITAL = 1000.0
RISK_PCT = 0.02
FEE_PCT = 0.001  # per side
TEST_DAYS = 30   # most recent 30 days of 1h bars (720 bars)


def _t(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def simulate(candles, signals, week_start_idx,
             capital=START_CAPITAL, risk_pct=RISK_PCT, fee_pct=FEE_PCT):
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
        if open_trade is not None:
            exit_price, outcome = None, None
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
                    raw = (exit_price - open_trade["entry"]) * open_trade["size"]
                else:
                    raw = (open_trade["entry"] - exit_price) * open_trade["size"]
                fees = (open_trade["entry"] + exit_price) * open_trade["size"] * fee_pct
                pnl = raw - fees
                cap += pnl
                trades.append({
                    "type": open_trade["type"], "entry_time": open_trade["t"],
                    "entry": open_trade["entry"], "exit_time": c.time,
                    "exit": exit_price, "outcome": outcome, "pnl": pnl,
                    "cap_after": cap,
                    "reason": open_trade["reason"],
                })
                open_trade = None
                if cap > equity_high:
                    equity_high = cap
                else:
                    dd = (equity_high - cap) / equity_high * 100.0
                    max_dd = max(max_dd, dd)

        sig = sigs_by_time.get(c.time)
        if sig is not None and open_trade is None:
            stop_dist = abs(sig.entry - sig.stop_loss)
            if stop_dist <= 0:
                continue
            size = (cap * risk_pct) / stop_dist
            open_trade = {
                "type": sig.type, "entry": sig.entry, "stop": sig.stop_loss,
                "target": sig.target, "size": size, "t": sig.time,
                "reason": sig.reason,
            }

    if open_trade is not None:
        last = candles[-1]
        if open_trade["type"] == "BUY":
            raw = (last.close - open_trade["entry"]) * open_trade["size"]
        else:
            raw = (open_trade["entry"] - last.close) * open_trade["size"]
        fees = (open_trade["entry"] + last.close) * open_trade["size"] * fee_pct
        pnl = raw - fees
        cap += pnl
        trades.append({
            "type": open_trade["type"], "entry_time": open_trade["t"],
            "entry": open_trade["entry"], "exit_time": last.time,
            "exit": last.close, "outcome": "OPEN", "pnl": pnl,
            "cap_after": cap, "reason": open_trade["reason"],
        })

    wins = sum(1 for t in trades if t["outcome"] == "WIN")
    losses = sum(1 for t in trades if t["outcome"] == "LOSS")
    open_count = sum(1 for t in trades if t["outcome"] == "OPEN")
    closed = wins + losses
    return {
        "trades": trades, "capital_end": cap,
        "total_pnl_pct": (cap - capital) / capital * 100.0,
        "count": len(trades), "wins": wins, "losses": losses, "open": open_count,
        "win_rate": (wins / closed * 100.0) if closed else 0.0,
        "max_dd_pct": max_dd,
    }


async def main():
    print(f"\n  MULTI-TF ADAPTIVE BACKTEST  |  {SYMBOL}  |  ${START_CAPITAL:.0f}  "
          f"|  Risk {RISK_PCT*100:.0f}%/trade  |  Fees {FEE_PCT*100:.1f}%/side")
    print(f"  Strategy logic: 1d trend regime + (4h confirmation) + 1h trigger\n")

    # Fetch all three timeframes in parallel.
    print("Fetching multi-TF data...")
    c1h, c4h, c1d = await asyncio.gather(
        fetch_klines(SYMBOL, "1h", 1000),
        fetch_klines(SYMBOL, "4h", 1000),
        fetch_klines(SYMBOL, "1d", 1000),
    )
    print(f"  1h: {len(c1h)} bars  ({_t(c1h[0].time)} -> {_t(c1h[-1].time)})")
    print(f"  4h: {len(c4h)} bars  ({_t(c4h[0].time)} -> {_t(c4h[-1].time)})")
    print(f"  1d: {len(c1d)} bars  ({_t(c1d[0].time)} -> {_t(c1d[-1].time)})")

    ctx = MTFContext(candles_1h=c1h, candles_4h=c4h, candles_1d=c1d)

    variants = [
        ("MTF Strict (1d + 4h + 1h, ADX>=20)", evaluate_strict),
        ("MTF 2-Screen (1d + 1h, ADX>=20)",    evaluate_2screen),
        ("MTF Relaxed (1d + 1h, ADX>=15)",     evaluate_relaxed),
        ("MTF Chop-Aware (RSI-confirmed BB)",  evaluate_chop_aware),
        ("MTF Chop-Only (no trend trades)",    evaluate_chop_only),
    ]

    # Test on multiple windows so we capture both choppy and trending periods.
    windows = [
        ("Last 30 days", min(30 * 24, len(c1h) - 50)),
        ("Last 42 days (full 1h history)", len(c1h) - 50),
    ]

    summary_table: dict[str, dict[str, float]] = {name: {} for name, _ in variants}

    for win_label, test_bars in windows:
        week_start_idx = len(c1h) - test_bars
        print(f"\n{'=' * 110}")
        print(f"  WINDOW: {win_label}  |  {_t(c1h[week_start_idx].time)} -> {_t(c1h[-1].time)}  ({test_bars} bars)")
        print(f"{'=' * 110}")
        print(f"{'Variant':<42}   {'Trades':>6} {'W':>3} {'L':>3} {'O':>3}   "
              f"{'Win %':>6}  {'PnL %':>8}  {'MaxDD %':>8}  {'End $':>9}")
        print("-" * 100)
        for name, fn in variants:
            signals = fn(ctx, week_start_idx)
            r = simulate(c1h, signals, week_start_idx)
            summary_table[name][win_label] = r["total_pnl_pct"]
            marker = " *" if r["total_pnl_pct"] > 0 else "  "
            print(f"{name:<42}{marker} {r['count']:>6} {r['wins']:>3} {r['losses']:>3} {r['open']:>3}   "
                  f"{r['win_rate']:>5.1f}%  {r['total_pnl_pct']:>+7.2f}%  {r['max_dd_pct']:>7.2f}%  "
                  f"${r['capital_end']:>7.2f}")

    # Cross-window summary
    print(f"\n\n{'=' * 110}")
    print(f"  CROSS-WINDOW PnL%   (* = profitable)")
    print(f"{'=' * 110}")
    headers = list(windows)
    print(f"{'Variant':<42}   " + "   ".join(f"{w[0]:>20}" for w in headers))
    print("-" * 100)
    for name, _ in variants:
        cells = "   ".join(f"{summary_table[name].get(w[0], 0):>+19.2f}%" for w in headers)
        print(f"{name:<42}   {cells}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
