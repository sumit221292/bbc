"""Today-only backtest across all strategies.

This is a small-sample observation, NOT a strategy validation. With only a few
hours of intraday data, results are dominated by luck. Use the 30-day or
multi-timeframe backtests for actual strategy comparison.

Single-TF strategies run on 15m (so ~96 bars per day are possible).
MTF strategies run on their native 1h entry timeframe.
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
from app.multi_tf import MTFContext
from app.strategies import list_mtf_metas, list_strategies, run_mtf


SYMBOL = "BTCUSDT"
START_CAPITAL = 1000.0
RISK_PCT = 0.02
FEE_PCT = 0.001  # per side


def _t(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M")


def simulate(candles, signals, start_idx,
             capital=START_CAPITAL, risk_pct=RISK_PCT, fee_pct=FEE_PCT):
    sigs_by_time = {
        s.time: s for s in signals
        if s.entry is not None and s.stop_loss is not None and s.target is not None
    }
    cap = capital
    trades = []
    open_trade = None

    for i in range(start_idx, len(candles)):
        c = candles[i]
        if open_trade is not None:
            exit_price, outcome = None, None
            if open_trade["type"] == "BUY":
                if c.low <= open_trade["stop"]:
                    exit_price, outcome = open_trade["stop"], "STOP"
                elif c.high >= open_trade["target"]:
                    exit_price, outcome = open_trade["target"], "WIN"
            else:
                if c.high >= open_trade["stop"]:
                    exit_price, outcome = open_trade["stop"], "STOP"
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
                    "type": open_trade["type"], "entry": open_trade["entry"],
                    "exit": exit_price, "outcome": outcome, "pnl": pnl,
                    "entry_time": open_trade["t"], "exit_time": c.time,
                })
                open_trade = None

        sig = sigs_by_time.get(c.time)
        if sig is not None and open_trade is None:
            stop_dist = abs(sig.entry - sig.stop_loss)
            if stop_dist <= 0:
                continue
            size = (cap * risk_pct) / stop_dist
            open_trade = {
                "type": sig.type, "entry": sig.entry, "stop": sig.stop_loss,
                "target": sig.target, "size": size, "t": sig.time,
            }

    # Mark to market open trade
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
            "type": open_trade["type"], "entry": open_trade["entry"],
            "exit": last.close, "outcome": "OPEN", "pnl": pnl,
            "entry_time": open_trade["t"], "exit_time": last.time,
        })

    wins = sum(1 for t in trades if t["outcome"] == "WIN")
    stops = sum(1 for t in trades if t["outcome"] == "STOP")
    open_count = sum(1 for t in trades if t["outcome"] == "OPEN")
    closed = wins + stops
    return {
        "trades": trades, "capital_end": cap,
        "total_pnl_pct": (cap - capital) / capital * 100.0,
        "count": len(trades), "wins": wins, "stops": stops, "open": open_count,
        "win_rate": (wins / closed * 100.0) if closed else 0.0,
    }


def _today_start_ts() -> int:
    now = datetime.now(timezone.utc)
    return int(datetime(now.year, now.month, now.day, tzinfo=timezone.utc).timestamp())


def _first_idx_at_or_after(candles, t: int) -> int:
    for i, c in enumerate(candles):
        if c.time >= t:
            return i
    return len(candles)


async def main():
    today_ts = _today_start_ts()
    today_str = datetime.fromtimestamp(today_ts, tz=timezone.utc).strftime("%Y-%m-%d")

    print(f"\n  TODAY-ONLY BACKTEST  |  {SYMBOL}  |  ${START_CAPITAL:.0f}  |  Risk {RISK_PCT*100:.0f}%/trade  "
          f"|  Fees {FEE_PCT*100:.1f}%/side")
    print(f"  Date: {today_str} UTC  (only signals fired AFTER 00:00 UTC count)\n")

    # Single-TF: 15m
    candles_15m = await fetch_klines(SYMBOL, "15m", 350)
    today_idx_15m = _first_idx_at_or_after(candles_15m, today_ts)
    bars_today_15m = len(candles_15m) - today_idx_15m
    print(f"15m bars today: {bars_today_15m}  ({_t(candles_15m[today_idx_15m].time)} -> {_t(candles_15m[-1].time)} UTC)")

    # MTF: 1h entry
    c1h, c4h, c1d = await asyncio.gather(
        fetch_klines(SYMBOL, "1h", 1000),
        fetch_klines(SYMBOL, "4h", 1000),
        fetch_klines(SYMBOL, "1d", 1000),
    )
    today_idx_1h = _first_idx_at_or_after(c1h, today_ts)
    bars_today_1h = len(c1h) - today_idx_1h
    ctx = MTFContext(candles_1h=c1h, candles_4h=c4h, candles_1d=c1d)
    print(f"1h bars today: {bars_today_1h}  ({_t(c1h[today_idx_1h].time) if bars_today_1h else 'n/a'} -> {_t(c1h[-1].time) if bars_today_1h else 'n/a'} UTC)\n")

    # Run all single-TF strategies on 15m
    rows = []
    for cls in list_strategies():
        signals = cls().evaluate(candles_15m)
        r = simulate(candles_15m, signals, today_idx_15m)
        rows.append((cls.name, "15m", r))

    # Run MTF strategies on 1h
    for meta in list_mtf_metas():
        signals = run_mtf(meta.id, ctx, start_idx=50)
        r = simulate(c1h, signals, today_idx_1h)
        rows.append((meta.name, "1h MTF", r))

    rows.sort(key=lambda x: x[2]["total_pnl_pct"], reverse=True)

    name_w = max(len(r[0]) for r in rows)
    print(f"{'Strategy':<{name_w}}   {'TF':>7}   {'Trades':>6} {'WIN':>4} {'STOP':>4} {'OPEN':>4}   "
          f"{'Win %':>6}  {'PnL %':>7}  {'End $':>9}")
    print("-" * (name_w + 65))
    for name, tf, r in rows:
        marker = " *" if r["total_pnl_pct"] > 0 else "  " if r["total_pnl_pct"] == 0 else "  "
        print(f"{name:<{name_w}}{marker} {tf:>7}   {r['count']:>6} {r['wins']:>4} {r['stops']:>4} {r['open']:>4}   "
              f"{r['win_rate']:>5.1f}%  {r['total_pnl_pct']:>+6.2f}%  ${r['capital_end']:>7.2f}")

    # Trade detail for any strategy that fired today
    print(f"\n\n  TRADE-BY-TRADE DETAIL (today only)\n")
    any_trades = False
    for name, tf, r in rows:
        if not r["trades"]:
            continue
        any_trades = True
        print(f"\n-- {name}  ({tf}) --")
        for t in r["trades"]:
            tag = "WIN " if t["outcome"] == "WIN" else "STOP" if t["outcome"] == "STOP" else "OPEN"
            print(f"   {t['type']:4}  {_t(t['entry_time'])} -> {_t(t['exit_time'])}   "
                  f"entry ${t['entry']:>9.2f}   exit ${t['exit']:>9.2f}   {tag}   "
                  f"PnL ${t['pnl']:>+6.2f}")
    if not any_trades:
        print("  (no strategy fired any signal today)")
    print()


if __name__ == "__main__":
    asyncio.run(main())
