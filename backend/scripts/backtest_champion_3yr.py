"""3-year backtest of the ★★★ Champion strategy across all timeframes.

Uses fetch_klines_paginated to walk back through Binance history in
1000-bar chunks. Realistic constraints:
  $1000 starting capital
  2% risk per trade
  0.2% round-trip fees (Binance spot)
  Per-regime RR: STRONG=2.5, MILD=2.0, CHOP=2.0  (Champion v10)
  ATR×1.0 stops (Champion v10)

Per-TF coverage:
  1d   3 years  (~1100 bars)   trade window: full 3y
  4h   3 years  (~6600 bars)
  1h   3 years  (~26300 bars)
  15m  6 months (~17500 bars)  -- shorter to keep fetch reasonable
  5m   1 month  (~8700 bars)

Run from the backend directory:
    .venv/Scripts/python.exe scripts/backtest_champion_3yr.py
"""
from __future__ import annotations

import asyncio
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.backtest import simulate
from app.binance import fetch_klines_paginated
from app.strategies.champion import Champion
from app.trade_status import annotate


SYMBOL = "BTCUSDT"
START_CAPITAL = 1000.0
RISK_PCT = 0.02
# Fee scenarios: spot is 0.1%/side, futures taker is 0.05%, maker 0.02%.
# Override via env var FEE_PCT, e.g. 0.0005 for futures.
import os
FEE_PCT = float(os.environ.get("FEE_PCT", "0.001"))

# (timeframe, total_bars_to_fetch, label)
WINDOWS = [
    ("1d",   1100,  "3 years"),
    ("4h",   6600,  "3 years"),
    ("1h",   26300, "3 years"),
    ("15m",  17500, "6 months"),
    ("5m",   8700,  "1 month"),
]

# Champion needs 220 bars warmup before it can fire (EMA200).
WARMUP = 220


def _t(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def max_drawdown(trades: list[dict], capital: float) -> float:
    """Walk the trade-by-trade equity curve and return peak-to-trough %."""
    eq = capital
    peak = capital
    max_dd = 0.0
    for t in trades:
        eq += t.get("pnl", 0.0)
        peak = max(peak, eq)
        if peak > 0:
            dd = (peak - eq) / peak * 100.0
            max_dd = max(max_dd, dd)
    return max_dd


async def run_one_window(interval: str, total_bars: int, label: str):
    print(f"\n  fetching {interval} (target {total_bars} bars, {label})…", flush=True)
    t0 = time.monotonic()
    candles = await fetch_klines_paginated(SYMBOL, interval, total_bars)
    fetch_s = time.monotonic() - t0
    if len(candles) < WARMUP + 50:
        print(f"  ⚠ only got {len(candles)} bars; skipping")
        return None

    print(f"  fetched {len(candles)} bars in {fetch_s:.1f}s "
          f"({_t(candles[0].time)} → {_t(candles[-1].time)})  evaluating…",
          flush=True)

    t0 = time.monotonic()
    signals = annotate(Champion().evaluate(candles), candles)
    eval_s = time.monotonic() - t0

    t0 = time.monotonic()
    r = simulate(candles, signals, start_idx=WARMUP, fee_pct=FEE_PCT)
    sim_s = time.monotonic() - t0
    dd = max_drawdown(
        # simulate doesn't expose individual trades — re-walk roughly via signals
        [{"pnl": s.pnl_pct or 0.0} for s in signals if s.status in ("WIN", "LOSS")],
        START_CAPITAL,
    )
    print(f"  evaluate: {eval_s:.1f}s  simulate: {sim_s:.2f}s")
    return {
        "interval": interval, "label": label,
        "bars": len(candles), "from": _t(candles[0].time), "to": _t(candles[-1].time),
        "trades": r["count"], "wins": r["wins"], "losses": r["losses"], "open": r["open"],
        "win_rate": r["win_rate"], "pnl_pct": r["total_pnl_pct"],
        "capital_end": r["capital_end"], "max_dd": dd,
    }


async def main():
    print(f"\n{'=' * 100}")
    print(f"  3-YEAR BACKTEST  ★★★ Champion (Adaptive Regime)  on  {SYMBOL}")
    print(f"  Starting capital ${START_CAPITAL:.0f}   2% risk/trade   {FEE_PCT*200:.2f}% round-trip fees")
    print(f"{'=' * 100}")

    results = []
    for interval, total_bars, label in WINDOWS:
        try:
            r = await run_one_window(interval, total_bars, label)
        except Exception as e:
            print(f"  ❌ {interval} failed: {e}")
            continue
        if r:
            results.append(r)

    print(f"\n\n{'=' * 100}")
    print(f"  SUMMARY")
    print(f"{'=' * 100}\n")
    header = (f"{'TF':>4}  {'Window':<10}  {'Bars':>6}  "
              f"{'From':<12}  {'To':<12}  "
              f"{'Trades':>6}  {'W':>4}  {'L':>4}  {'Open':>4}  "
              f"{'Win %':>6}  {'PnL %':>9}  {'End $':>9}  {'MaxDD %':>8}")
    print(header)
    print("-" * len(header))
    for r in results:
        print(
            f"{r['interval']:>4}  {r['label']:<10}  {r['bars']:>6}  "
            f"{r['from']:<12}  {r['to']:<12}  "
            f"{r['trades']:>6}  {r['wins']:>4}  {r['losses']:>4}  {r['open']:>4}  "
            f"{r['win_rate']:>5.1f}%  {r['pnl_pct']:>+8.2f}%  "
            f"${r['capital_end']:>8.2f}  {r['max_dd']:>7.2f}%"
        )
    if results:
        avg_pnl = sum(r['pnl_pct'] for r in results) / len(results)
        print(f"\n  Average PnL across all timeframes: {avg_pnl:+.2f}%")
    print()


if __name__ == "__main__":
    asyncio.run(main())
