"""Cross-strategy backtest with trail vs no-trail comparison.

Runs every registered strategy (single-TF + MTF) across the top-N
USDT pairs filtered to current price >= $1. For each (strategy, coin)
runs simulate() twice -- once with trail=False (old worker behaviour),
once with trail=True (post-cooldown-removal ratchet-trail) -- so we
can see per-strategy impact rather than just Confluence's slice.

Env vars:
  LIMIT=20                  how many coins to scan
  MIN_PRICE=1.0             $-floor for inclusion
  FEE_PCT=0.001             fee per side (spot)

Usage:
  .venv/Scripts/python.exe scripts/backtest_all_strategies.py
"""
from __future__ import annotations

import asyncio
import os
import sys
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
from app.multi_tf import MTFContext
from app.strategies import (
    is_mtf, list_mtf_metas, list_strategies, run_mtf,
)
from app.trade_status import annotate


WARMUP = 220
INTERVAL_1H = "1h"
START_CAPITAL = 1000.0
RISK_PCT = 0.02

# Per-TF bar counts to cover ~1 year of history with indicator warmup.
BARS_1H = 8760 + WARMUP
BARS_4H = 2190 + 60
BARS_1D = 365 + 30

FEE_PCT = float(os.environ.get("FEE_PCT", "0.001"))
LIMIT = int(os.environ.get("LIMIT", "20"))
MIN_PRICE = float(os.environ.get("MIN_PRICE", "1.0"))
_STABLE_BASES = {"USDC", "BUSD", "TUSD", "FDUSD", "USDP", "DAI", "USDS", "PYUSD"}


async def _discover_symbols() -> list[str]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        info = (await client.get(f"{settings.binance_rest}/api/v3/exchangeInfo")).json()
        tickers = (await client.get(f"{settings.binance_rest}/api/v3/ticker/24hr")).json()
    price = {t["symbol"]: float(t.get("lastPrice", 0) or 0) for t in tickers}
    vol = {t["symbol"]: float(t.get("quoteVolume", 0) or 0) for t in tickers}
    eligible = []
    for s in info.get("symbols", []):
        sym = s["symbol"]
        if s.get("quoteAsset") != "USDT": continue
        if s.get("status") != "TRADING": continue
        if not s.get("isSpotTradingAllowed", True): continue
        if price.get(sym, 0.0) < MIN_PRICE: continue
        if s["baseAsset"] in _STABLE_BASES: continue
        eligible.append({"symbol": sym, "vol": vol.get(sym, 0.0)})
    eligible.sort(key=lambda p: -p["vol"])
    return [e["symbol"] for e in eligible[:LIMIT]]


async def _fetch_candles(symbol: str) -> dict:
    """Pull 1h / 4h / 1d candles once per coin. MTF strategies need all
    three; single-TF strategies only touch 1h."""
    c1h, c4h, c1d = await asyncio.gather(
        fetch_klines_paginated(symbol, "1h", BARS_1H),
        fetch_klines_paginated(symbol, "4h", BARS_4H),
        fetch_klines_paginated(symbol, "1d", BARS_1D),
    )
    return {"1h": c1h, "4h": c4h, "1d": c1d}


def _signals_for(strat_id: str, strat_cls_or_none, candles: dict):
    """Evaluate one strategy on a coin's candles, returning annotated
    signals indexed against the 1h frame (so simulate() runs on the
    1h ladder for both single-TF and MTF cases)."""
    if is_mtf(strat_id):
        ctx = MTFContext(
            candles_1h=candles["1h"], candles_4h=candles["4h"], candles_1d=candles["1d"],
        )
        raw = run_mtf(strat_id, ctx, start_idx=WARMUP)
        return annotate(raw, candles["1h"])
    # single-TF strategy class
    raw = strat_cls_or_none().evaluate(candles["1h"])
    return annotate(raw, candles["1h"])


def _run_pair(candles_1h, signals, strategy_supports_trail: bool):
    """Run BOTH trail modes so the report can show what trail did vs
    the per-strategy live decision. `live_choice` field marks which
    one the deployed alert_loop will actually use for this strategy."""
    nt = simulate(candles_1h, signals, start_idx=WARMUP, fee_pct=FEE_PCT,
                  capital=START_CAPITAL, risk_pct=RISK_PCT, trail=False)
    wt = simulate(candles_1h, signals, start_idx=WARMUP, fee_pct=FEE_PCT,
                  capital=START_CAPITAL, risk_pct=RISK_PCT, trail=True)
    nt["signals"] = len(signals)
    wt["signals"] = len(signals)
    nt["live"] = not strategy_supports_trail
    wt["live"] = strategy_supports_trail
    return nt, wt


async def main():
    symbols = await _discover_symbols()
    print(f"Discovered {len(symbols)} coins (price >= ${MIN_PRICE:.2f}, top-by-volume):")
    print("  " + ", ".join(symbols))

    print(f"\nFetching 1h / 4h / 1d candles for each coin (this takes a few minutes)...")
    candle_cache: dict[str, dict] = {}
    for i, sym in enumerate(symbols, 1):
        print(f"  [{i}/{len(symbols)}] {sym}...", end=" ", flush=True)
        try:
            candle_cache[sym] = await _fetch_candles(sym)
            print(f"1h={len(candle_cache[sym]['1h'])} 4h={len(candle_cache[sym]['4h'])} 1d={len(candle_cache[sym]['1d'])}")
        except Exception as e:
            print(f"FAILED: {e}")

    # Build strategy roster.
    single_tf = list(list_strategies())
    mtf_metas = list_mtf_metas()
    print(f"\nRunning {len(single_tf)} single-TF + {len(mtf_metas)} MTF strategies "
          f"across {len(candle_cache)} coins...")

    # results: { strategy_id: [(symbol, no_trail, trail), ...] }
    by_strategy: dict[str, list] = {}
    pair_deltas: list = []  # (delta_pnl, strategy_id, symbol)

    # supports_trail flag drives which mode the LIVE worker will use.
    # MTF metas default to False (alert_loop has the same fallback).
    trail_flag: dict[str, bool] = {}
    for strat_cls in single_tf:
        trail_flag[strat_cls.id] = bool(getattr(strat_cls, "supports_trail", False))
    for meta in mtf_metas:
        trail_flag[meta.id] = False

    for strat_cls in single_tf:
        sid = strat_cls.id
        rows = []
        for sym, candles in candle_cache.items():
            try:
                sigs = _signals_for(sid, strat_cls, candles)
                if not sigs:
                    continue
                nt, wt = _run_pair(candles["1h"], sigs, trail_flag[sid])
                rows.append((sym, nt, wt))
                pair_deltas.append((wt["total_pnl_pct"] - nt["total_pnl_pct"], sid, sym))
            except Exception as e:
                print(f"  !! {sid}/{sym}: {e}")
        by_strategy[sid] = rows

    for meta in mtf_metas:
        sid = meta.id
        rows = []
        for sym, candles in candle_cache.items():
            try:
                sigs = _signals_for(sid, None, candles)
                if not sigs:
                    continue
                nt, wt = _run_pair(candles["1h"], sigs, trail_flag[sid])
                rows.append((sym, nt, wt))
                pair_deltas.append((wt["total_pnl_pct"] - nt["total_pnl_pct"], sid, sym))
            except Exception as e:
                print(f"  !! {sid}/{sym}: {e}")
        by_strategy[sid] = rows

    # ------------- PER-STRATEGY ROLL-UP -------------
    print(f"\n{'=' * 100}")
    print(f"  PER-STRATEGY IMPACT (avg across {len(candle_cache)} coins, 1y, 1h trigger)")
    print(f"{'=' * 100}")
    print(f"{'Strategy':<22}  {'Live':>4}  {'Coins':>5}  {'AvgSigs':>7}  "
          f"{'NoTrail WR':>10}  {'NoTrail PnL':>12}   "
          f"{'Trail WR':>9}  {'Trail PnL':>10}   "
          f"{'Δ PnL':>8}")
    print("-" * 110)

    rollup_rows = []
    for sid, rows in by_strategy.items():
        if not rows:
            continue
        n = len(rows)
        avg_sigs = sum(r[1]["signals"] for r in rows) / n
        avg_nt_pnl = sum(r[1]["total_pnl_pct"] for r in rows) / n
        avg_wt_pnl = sum(r[2]["total_pnl_pct"] for r in rows) / n
        nt_wr_rows = [r[1]["win_rate"] for r in rows if r[1]["wins"] + r[1]["losses"] > 0]
        wt_wr_rows = [r[2]["win_rate"] for r in rows if r[2]["wins"] + r[2]["losses"] > 0]
        avg_nt_wr = sum(nt_wr_rows) / len(nt_wr_rows) if nt_wr_rows else 0.0
        avg_wt_wr = sum(wt_wr_rows) / len(wt_wr_rows) if wt_wr_rows else 0.0
        rollup_rows.append((sid, n, avg_sigs, avg_nt_wr, avg_nt_pnl, avg_wt_wr, avg_wt_pnl))

    # Sort by trail impact (delta) descending so the biggest gains appear at top.
    rollup_rows.sort(key=lambda r: -(r[6] - r[4]))

    for sid, n, avg_sigs, nt_wr, nt_pnl, wt_wr, wt_pnl in rollup_rows:
        d = wt_pnl - nt_pnl
        marker = " ✅" if d > 0.5 else (" ❌" if d < -0.5 else "")
        live = "TRAIL" if trail_flag.get(sid, False) else "  -  "
        print(
            f"{sid:<22}  {live:>4}  {n:>5}  {avg_sigs:>7.1f}  "
            f"{nt_wr:>9.1f}%  {nt_pnl:>+11.2f}%   "
            f"{wt_wr:>8.1f}%  {wt_pnl:>+9.2f}%   "
            f"{d:>+7.2f}pp{marker}"
        )

    # ------------- TOP 10 PAIR IMPROVEMENTS -------------
    pair_deltas.sort(reverse=True)
    print(f"\n{'=' * 100}")
    print(f"  TOP 10 (strategy, coin) PAIRS WHERE TRAIL HELPED MOST")
    print(f"{'=' * 100}")
    print(f"{'Strategy':<22}  {'Coin':<10}  {'Δ PnL':>8}")
    print("-" * 50)
    for d, sid, sym in pair_deltas[:10]:
        if d <= 0:
            break
        print(f"{sid:<22}  {sym:<10}  {d:>+7.2f}pp")

    # ------------- BOTTOM 10 (TRAIL HURT) -------------
    print(f"\n{'=' * 100}")
    print(f"  BOTTOM 10 (strategy, coin) PAIRS WHERE TRAIL HURT MOST")
    print(f"{'=' * 100}")
    print(f"{'Strategy':<22}  {'Coin':<10}  {'Δ PnL':>8}")
    print("-" * 50)
    for d, sid, sym in sorted(pair_deltas)[:10]:
        if d >= 0:
            break
        print(f"{sid:<22}  {sym:<10}  {d:>+7.2f}pp")

    # ------------- OVERALL ROLL-UP -------------
    if pair_deltas:
        all_n = len(pair_deltas)
        avg_d = sum(d for d, _, _ in pair_deltas) / all_n
        helped = sum(1 for d, _, _ in pair_deltas if d > 0.5)
        hurt = sum(1 for d, _, _ in pair_deltas if d < -0.5)
        flat = all_n - helped - hurt
        print(f"\n{'=' * 100}")
        print(f"  OVERALL: {all_n} (strategy, coin) pairs evaluated")
        print(f"  Trail helped: {helped} ({helped / all_n * 100:.1f}%)   "
              f"Hurt: {hurt} ({hurt / all_n * 100:.1f}%)   "
              f"Flat: {flat} ({flat / all_n * 100:.1f}%)")
        print(f"  Avg Δ PnL across all pairs: {avg_d:+.2f}pp")

    # ------------- EFFECTIVE PORTFOLIO (per-strategy live choice) -------------
    # Pull the PnL that the LIVE worker would actually realise: trail
    # mode for strategies whose supports_trail=True, no-trail for the
    # rest. This is the number that matters after the per-strategy gate.
    eff_nt_total = eff_live_total = 0.0
    eff_n = 0
    for sid, rows in by_strategy.items():
        flag = trail_flag.get(sid, False)
        for _, nt, wt in rows:
            eff_nt_total += nt["total_pnl_pct"]  # baseline: trail off everywhere
            eff_live_total += wt["total_pnl_pct"] if flag else nt["total_pnl_pct"]
            eff_n += 1
    if eff_n:
        delta = eff_live_total - eff_nt_total
        print(f"\n{'=' * 100}")
        print(f"  EFFECTIVE PORTFOLIO (per-strategy gating: trail only on supports_trail=True)")
        print(f"{'=' * 100}")
        print(f"  No-trail baseline (everywhere)      : avg {eff_nt_total / eff_n:+.2f}% per pair")
        print(f"  Live worker (gated per-strategy)    : avg {eff_live_total / eff_n:+.2f}% per pair")
        print(f"  Gating gain vs no-trail baseline    : {delta / eff_n:+.2f}pp per pair "
              f"(total {delta:+.2f}pp across {eff_n} pairs)")


if __name__ == "__main__":
    asyncio.run(main())
