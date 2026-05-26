"""Backtest Confluence (3-of-5 voting) across many USDT pairs on 1h.

By default this scans the top-N highest-volume USDT pairs on Binance
filtered to current price >= $1. Sub-dollar coins (DOGE/PEPE/SHIB) are
deliberately skipped: their tick-size precision causes stop / target
slippage that wrecks short backtests of 0.1% fee-rounding margins, so
real returns don't match the backtest numbers.

Env vars:
  SYMBOLS=BTCUSDT,ETHUSDT   override the auto-scan with a hand-picked list
  LIMIT=20                  how many coins to scan (default 20)
  MIN_PRICE=1.0             $-floor for inclusion (default 1.0)
  FEE_PCT=0.001             fee per side (default 0.1% spot)
  VERBOSE=1                 print quarterly breakdown per coin

Usage:
  .venv/Scripts/python.exe scripts/backtest_confluence.py
  SYMBOLS=BTCUSDT,ETHUSDT .venv/Scripts/python.exe scripts/backtest_confluence.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.backtest import simulate
from app.binance import fetch_klines_paginated
from app.config import settings
from app.strategies.confluence import Confluence
from app.trade_status import annotate


INTERVAL = "1h"
TOTAL_BARS = 8760 + 220   # 1y on 1h + indicator warmup
WARMUP = 220
START_CAPITAL = 1000.0
RISK_PCT = 0.02

FEE_PCT = float(os.environ.get("FEE_PCT", "0.001"))
LIMIT = int(os.environ.get("LIMIT", "20"))
MIN_PRICE = float(os.environ.get("MIN_PRICE", "1.0"))
VERBOSE = os.environ.get("VERBOSE", "") not in ("", "0", "false", "False")
SYMBOLS_OVERRIDE = [s.strip().upper() for s in os.environ.get("SYMBOLS", "").split(",") if s.strip()]


def _t(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


async def _discover_symbols() -> list[str]:
    """Pull top-N USDT pairs from Binance whose last price >= MIN_PRICE,
    sorted by 24h quote volume (most-liquid first). Tickers below the
    floor are filtered out -- their tick size causes precision issues
    that don't match the backtest's assumptions."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        info = (await client.get(f"{settings.binance_rest}/api/v3/exchangeInfo")).json()
        tickers = (await client.get(f"{settings.binance_rest}/api/v3/ticker/24hr")).json()

    price_by_sym = {t["symbol"]: float(t.get("lastPrice", 0) or 0) for t in tickers}
    vol_by_sym = {t["symbol"]: float(t.get("quoteVolume", 0) or 0) for t in tickers}

    eligible = []
    for s in info.get("symbols", []):
        sym = s["symbol"]
        if s.get("quoteAsset") != "USDT": continue
        if s.get("status") != "TRADING": continue
        if not s.get("isSpotTradingAllowed", True): continue
        price = price_by_sym.get(sym, 0.0)
        if price < MIN_PRICE: continue
        # Skip stablecoins disguised as USDT pairs (USDC/USDT etc are ~$1
        # but not interesting to backtest -- no price movement).
        base = s["baseAsset"]
        if base in ("USDC", "BUSD", "TUSD", "FDUSD", "USDP", "DAI", "USDS"):
            continue
        eligible.append({
            "symbol": sym, "price": price, "vol": vol_by_sym.get(sym, 0.0),
        })

    eligible.sort(key=lambda p: -p["vol"])
    return [e["symbol"] for e in eligible[:LIMIT]]


async def backtest_symbol(symbol: str):
    candles = await fetch_klines_paginated(symbol, INTERVAL, TOTAL_BARS)
    signals = annotate(Confluence().evaluate(candles), candles)

    if VERBOSE:
        print(f"\n{'=' * 78}")
        print(f"  {symbol}  ({INTERVAL})")
        print(f"{'=' * 78}")
        print(f"Loaded {len(candles)} bars: {_t(candles[0].time)} -> {_t(candles[-1].time)}")
        n_buy = sum(1 for s in signals if s.type == "BUY")
        n_sell = sum(1 for s in signals if s.type == "SELL")
        print(f"Confluence emitted {len(signals)} signals ({n_buy} BUY / {n_sell} SELL)")
    # Will return both no-trail (old behaviour) AND trail (new) so the
    # caller can show side-by-side improvement.

        usable = candles[WARMUP:]
        quarter = len(usable) // 4
        windows = [
            ("Q1", usable[0:quarter]),
            ("Q2", usable[quarter:2*quarter]),
            ("Q3", usable[2*quarter:3*quarter]),
            ("Q4", usable[3*quarter:]),
        ]
        print(f"\n{'Window':<6}  {'From':<12}  {'To':<12}  {'Trades':>6}  {'W':>4}  "
              f"{'L':>4}  {'WR%':>6}  {'PnL%':>9}  {'End $':>9}")
        print("-" * 78)
        for label, win in windows:
            if not win:
                continue
            win_start_t, win_end_t = win[0].time, win[-1].time
            win_signals = [s for s in signals if win_start_t <= s.time <= win_end_t]
            start_idx = next((i for i, c in enumerate(candles) if c.time >= win_start_t), 0)
            sub = candles[max(0, start_idx - WARMUP):]
            sub_idx = next((i for i, c in enumerate(sub) if c.time >= win_start_t), 0)
            r = simulate(sub, win_signals, start_idx=sub_idx, fee_pct=FEE_PCT,
                         capital=START_CAPITAL, risk_pct=RISK_PCT)
            print(
                f"{label:<6}  {_t(win[0].time):<12}  {_t(win[-1].time):<12}  "
                f"{r['count']:>6}  {r['wins']:>4}  {r['losses']:>4}  "
                f"{r['win_rate']:>5.1f}%  {r['total_pnl_pct']:>+8.2f}%  "
                f"${r['capital_end']:>8.2f}"
            )
        print("-" * 78)

    notrail = simulate(candles, signals, start_idx=WARMUP, fee_pct=FEE_PCT,
                       capital=START_CAPITAL, risk_pct=RISK_PCT, trail=False)
    withtrail = simulate(candles, signals, start_idx=WARMUP, fee_pct=FEE_PCT,
                         capital=START_CAPITAL, risk_pct=RISK_PCT, trail=True)
    notrail["signals"] = len(signals)
    withtrail["signals"] = len(signals)
    return symbol, notrail, withtrail


async def main():
    if SYMBOLS_OVERRIDE:
        symbols = SYMBOLS_OVERRIDE
        print(f"\nSYMBOLS override: {symbols}")
    else:
        print(f"\nDiscovering top-{LIMIT} USDT pairs (price >= ${MIN_PRICE:.2f}, by 24h volume)...")
        symbols = await _discover_symbols()
        print(f"Picked {len(symbols)} coins: {', '.join(symbols)}")

    print(f"\nBacktest: Confluence on {INTERVAL}, 1 year")
    print(f"Capital ${START_CAPITAL:.0f}, risk {RISK_PCT * 100:.1f}%/trade, "
          f"fee {FEE_PCT * 100:.2f}%/side")

    rows = []  # (symbol, no_trail_result, trail_result)
    for i, symbol in enumerate(symbols, 1):
        try:
            print(f"  [{i}/{len(symbols)}] {symbol}...", end=" ", flush=True)
            sym, nt, wt = await backtest_symbol(symbol)
            rows.append((sym, nt, wt))
            if not VERBOSE:
                d_pnl = wt["total_pnl_pct"] - nt["total_pnl_pct"]
                d_wr = wt["win_rate"] - nt["win_rate"]
                print(f"NoTrail PnL {nt['total_pnl_pct']:>+7.2f}% WR {nt['win_rate']:>5.1f}%  "
                      f"->  Trail PnL {wt['total_pnl_pct']:>+7.2f}% WR {wt['win_rate']:>5.1f}%  "
                      f"(Δ {d_pnl:+.2f}pp PnL, {d_wr:+.1f}pp WR)")
        except Exception as e:
            print(f"FAILED: {e}")

    # Sort by trail's PnL descending so the best post-change performers
    # surface first.
    rows.sort(key=lambda x: -x[2]["total_pnl_pct"])

    print(f"\n{'=' * 92}")
    print(f"  CROSS-COIN SIDE-BY-SIDE (1y, {INTERVAL})  --  no trail (OLD) vs trail (NEW)")
    print(f"{'=' * 92}")
    print(f"{'Symbol':<10}  {'Sigs':>5}  "
          f"{'NoTrail WR':>10}  {'NoTrail PnL':>12}   "
          f"{'Trail WR':>9}  {'Trail PnL':>10}   "
          f"{'Δ PnL':>8}")
    print("-" * 92)
    winners = losers = breakeven = 0
    sum_nt_pnl = sum_wt_pnl = 0.0
    sum_nt_wr_n = sum_nt_wr = 0
    sum_wt_wr_n = sum_wt_wr = 0
    for sym, nt, wt in rows:
        d = wt["total_pnl_pct"] - nt["total_pnl_pct"]
        print(
            f"{sym:<10}  {wt['signals']:>5}  "
            f"{nt['win_rate']:>9.1f}%  {nt['total_pnl_pct']:>+11.2f}%   "
            f"{wt['win_rate']:>8.1f}%  {wt['total_pnl_pct']:>+9.2f}%   "
            f"{d:>+7.2f}pp"
        )
        sum_nt_pnl += nt["total_pnl_pct"]
        sum_wt_pnl += wt["total_pnl_pct"]
        if nt["wins"] + nt["losses"] > 0:
            sum_nt_wr += nt["win_rate"]; sum_nt_wr_n += 1
        if wt["wins"] + wt["losses"] > 0:
            sum_wt_wr += wt["win_rate"]; sum_wt_wr_n += 1
        if wt["total_pnl_pct"] > 0.5: winners += 1
        elif wt["total_pnl_pct"] < -0.5: losers += 1
        else: breakeven += 1
    print("-" * 92)
    n = len(rows)
    if n > 0:
        avg_nt_pnl = sum_nt_pnl / n
        avg_wt_pnl = sum_wt_pnl / n
        avg_nt_wr = sum_nt_wr / max(1, sum_nt_wr_n)
        avg_wt_wr = sum_wt_wr / max(1, sum_wt_wr_n)
        print(f"\nWith trail -- Profitable: {winners}/{n}  Breakeven: {breakeven}  Loss: {losers}")
        print(f"Avg PnL/coin:  NoTrail {avg_nt_pnl:+.2f}%   ->   Trail {avg_wt_pnl:+.2f}%   "
              f"(Δ {avg_wt_pnl - avg_nt_pnl:+.2f}pp)")
        print(f"Avg WR     :  NoTrail {avg_nt_wr:.1f}%      ->   Trail {avg_wt_wr:.1f}%      "
              f"(Δ {avg_wt_wr - avg_nt_wr:+.1f}pp)")


if __name__ == "__main__":
    asyncio.run(main())
