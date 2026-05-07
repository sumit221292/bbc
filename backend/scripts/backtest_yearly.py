"""Year-by-year performance check for ★★★ Champion on BTCUSDT 1d.

Splits the 3-year history into three 1-year windows so we can see whether
the strategy's edge is consistent or just rode one good regime.

Usage:
  FEE_PCT=0.001  .venv/Scripts/python.exe scripts/backtest_yearly.py  # spot
  FEE_PCT=0.0005 .venv/Scripts/python.exe scripts/backtest_yearly.py  # futures taker
  FEE_PCT=0.0002 .venv/Scripts/python.exe scripts/backtest_yearly.py  # futures maker
"""
from __future__ import annotations

import asyncio
import os
import sys
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
FEE_PCT = float(os.environ.get("FEE_PCT", "0.001"))
WARMUP = 220


def _t(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


async def main():
    # 3 years on 1d = ~1100 bars + 220 warmup buffer
    candles = await fetch_klines_paginated(SYMBOL, "1d", 1320)
    print(f"Loaded {len(candles)} 1d bars: {_t(candles[0].time)} -> {_t(candles[-1].time)}")

    signals = annotate(Champion().evaluate(candles), candles)

    # Three 1-year windows: split the candle range into thirds (skip warmup).
    usable = candles[WARMUP:]
    third = len(usable) // 3
    windows = [
        ("Year 1", usable[0 * third: 1 * third]),
        ("Year 2", usable[1 * third: 2 * third]),
        ("Year 3", usable[2 * third:]),
    ]

    print(f"\nFee model: {FEE_PCT * 100:.2f}% per side ({FEE_PCT * 200:.2f}% round-trip)")
    print(f"\n{'Window':<8}  {'From':<12}  {'To':<12}  {'Trades':>6}  {'W':>4}  "
          f"{'L':>4}  {'WR%':>6}  {'PnL%':>9}  {'End $':>9}")
    print("-" * 80)

    for label, win in windows:
        if not win:
            continue
        start_idx = next((i for i, c in enumerate(candles) if c.time >= win[0].time), 0)
        # Re-filter signals to this window only
        win_start_t, win_end_t = win[0].time, win[-1].time
        win_signals = [s for s in signals if win_start_t <= s.time <= win_end_t]
        # Slice candles: start from window start, but keep warmup for indicators
        sub = candles[max(0, start_idx - WARMUP):]
        sub_idx = next((i for i, c in enumerate(sub) if c.time >= win_start_t), 0)
        r = simulate(sub, win_signals, start_idx=sub_idx, fee_pct=FEE_PCT)
        print(
            f"{label:<8}  {_t(win[0].time):<12}  {_t(win[-1].time):<12}  "
            f"{r['count']:>6}  {r['wins']:>4}  {r['losses']:>4}  "
            f"{r['win_rate']:>5.1f}%  {r['total_pnl_pct']:>+8.2f}%  "
            f"${r['capital_end']:>8.2f}"
        )


if __name__ == "__main__":
    asyncio.run(main())
