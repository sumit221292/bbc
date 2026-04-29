"""Market outlook for next session — NOT a price prediction.

Reports current regime, key levels, volatility, and what each strategy is
currently saying. Use it to PREPARE a plan, not to predict the future.

Output sections:
  1. Where we are right now (price, today's range, yesterday's range)
  2. Regime analysis on 1d / 4h / 1h
  3. Key levels (swings, EMAs, Bollinger, S/R)
  4. Volatility (ATR-based expected daily range)
  5. Strategy bias snapshot — what each strategy currently signals
  6. Trade plan: conditional triggers (if X then Y)
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.binance import fetch_klines
from app.indicators import adx, atr, bollinger, ema, rsi
from app.multi_tf import MTFContext
from app.strategies import list_mtf_metas, list_strategies, run_mtf
from app.trade_status import annotate


SYMBOL = "BTCUSDT"


def fmt(v, d=2):
    if v is None:
        return "—"
    return f"${v:,.{d}f}"


def pct(v, d=2):
    if v is None:
        return "—"
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.{d}f}%"


async def main():
    print(f"\n{'=' * 80}")
    print(f"  {SYMBOL} MARKET OUTLOOK")
    print(f"  Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC")
    print(f"{'=' * 80}\n")

    # Fetch everything in parallel
    c15m, c1h, c4h, c1d = await asyncio.gather(
        fetch_klines(SYMBOL, "15m", 300),
        fetch_klines(SYMBOL, "1h", 1000),
        fetch_klines(SYMBOL, "4h", 1000),
        fetch_klines(SYMBOL, "1d", 1000),
    )

    last = c1h[-1]
    today_d = c1d[-1]   # may be partial (still forming today)
    yest_d = c1d[-2]

    print("--- WHERE WE ARE NOW ---")
    print(f"Current price:        {fmt(last.close)}")
    chg_today = (today_d.close - today_d.open) / today_d.open * 100.0
    chg_yest = (yest_d.close - yest_d.open) / yest_d.open * 100.0
    print(f"Today (so far):       open {fmt(today_d.open)}  high {fmt(today_d.high)}  "
          f"low {fmt(today_d.low)}  close {fmt(today_d.close)}  ({pct(chg_today)})")
    print(f"Yesterday:            open {fmt(yest_d.open)}  high {fmt(yest_d.high)}  "
          f"low {fmt(yest_d.low)}  close {fmt(yest_d.close)}  ({pct(chg_yest)})")

    # ---- Regime ----
    ctx = MTFContext(candles_1h=c1h, candles_4h=c4h, candles_1d=c1d)
    d_regime = ctx.daily_regime_at(last.time, adx_min=20.0)
    d_regime_relaxed = ctx.daily_regime_at(last.time, adx_min=15.0)
    h4_regime = ctx.h4_regime_at(last.time)

    print("\n--- REGIME (multi-TF) ---")
    closes_1d = [c.close for c in c1d]
    highs_1d = [c.high for c in c1d]
    lows_1d = [c.low for c in c1d]
    d_e50 = ema(closes_1d, 50)
    d_e200 = ema(closes_1d, 200)
    d_adx, _, _ = adx(highs_1d, lows_1d, closes_1d, 14)
    print(f"Daily (1d):           {d_regime}   (ADX={d_adx[-1]:.1f}, EMA50={fmt(d_e50[-1])}, EMA200={fmt(d_e200[-1])})")
    if d_regime != d_regime_relaxed:
        print(f"  -- with ADX>=15:    {d_regime_relaxed}  (weaker trend definition)")
    print(f"4h:                   {h4_regime}")

    # ---- Key levels ----
    bbu_d, bbm_d, bbl_d = bollinger(closes_1d, 20, 2.0)
    atr_d = atr(highs_1d, lows_1d, closes_1d, 14)
    rsi_d = rsi(closes_1d, 14)
    swing_high = max(c.high for c in c1d[-20:])
    swing_low = min(c.low for c in c1d[-20:])

    print("\n--- KEY LEVELS (1d) ---")
    print(f"20-day swing HIGH:    {fmt(swing_high)}     (resistance)")
    print(f"20-day swing LOW:     {fmt(swing_low)}     (support)")
    print(f"Bollinger upper:      {fmt(bbu_d[-1])}")
    print(f"Bollinger middle:     {fmt(bbm_d[-1])}     (mean)")
    print(f"Bollinger lower:      {fmt(bbl_d[-1])}")
    print(f"EMA20 (1d):           {fmt(ema(closes_1d, 20)[-1])}")
    print(f"EMA50 (1d):           {fmt(d_e50[-1])}")
    print(f"EMA200 (1d):          {fmt(d_e200[-1])}")
    print(f"Daily RSI(14):        {rsi_d[-1]:.1f}  ({'oversold' if rsi_d[-1] < 30 else 'overbought' if rsi_d[-1] > 70 else 'neutral'})")

    # ---- Volatility ----
    print("\n--- VOLATILITY (next 24h expectation) ---")
    daily_atr = atr_d[-1]
    print(f"Daily ATR(14):        {fmt(daily_atr)}     (typical daily range)")
    print(f"Expected range:       {fmt(last.close - daily_atr)} - {fmt(last.close + daily_atr)}  "
          f"(±{daily_atr/last.close*100:.2f}%)")
    print(f"68% confidence:       {fmt(last.close - daily_atr * 0.7)} - {fmt(last.close + daily_atr * 0.7)}")
    print(f"95% confidence:       {fmt(last.close - daily_atr * 1.4)} - {fmt(last.close + daily_atr * 1.4)}")

    # ---- Strategy bias snapshot ----
    print("\n--- WHAT EACH STRATEGY SAYS RIGHT NOW (1h timeframe) ---")
    print(f"{'Strategy':<38}   {'Last signal':>12}   {'Status':>6}   {'Bars ago':>9}")
    print("-" * 80)

    last_idx = len(c1h) - 1

    for cls in list_strategies():
        signals = annotate(cls().evaluate(c1h), c1h)
        if not signals:
            print(f"{cls.name:<38}   {'—':>12}   {'HOLD':>6}   {'—':>9}")
            continue
        s = signals[-1]
        try:
            sig_idx = next(i for i, c in enumerate(c1h) if c.time == s.time)
            bars_ago = last_idx - sig_idx
        except StopIteration:
            bars_ago = -1
        print(f"{cls.name:<38}   {s.type:>12}   {s.status or '—':>6}   {bars_ago:>9}")

    # MTF strategies
    print()
    for meta in list_mtf_metas():
        signals = annotate(run_mtf(meta.id, ctx, start_idx=50), c1h)
        if not signals:
            print(f"{meta.name:<38}   {'—':>12}   {'HOLD':>6}   {'—':>9}")
            continue
        s = signals[-1]
        try:
            sig_idx = next(i for i, c in enumerate(c1h) if c.time == s.time)
            bars_ago = last_idx - sig_idx
        except StopIteration:
            bars_ago = -1
        print(f"{meta.name:<38}   {s.type:>12}   {s.status or '—':>6}   {bars_ago:>9}")

    # ---- Trade plan ----
    print("\n--- TRADE PLAN FOR NEXT SESSION ---")
    if d_regime == "BULL":
        print(f"BIAS: LONG only (daily uptrend, ADX confirms)")
        print(f"Entry triggers (any one):")
        print(f"  - Pullback to EMA20 (~{fmt(ema(closes_1d, 20)[-1])}) and bounce")
        print(f"  - 1h RSI drops below 40 then turns up")
        print(f"  - Bollinger lower band tag with bullish close")
        print(f"Stop: 1.5x ATR below entry (~{fmt(daily_atr * 1.5)} risk)")
        print(f"Target: 2R minimum (target = entry + 3x ATR roughly)")
        print(f"Invalidation: daily close below EMA50 ({fmt(d_e50[-1])})")
    elif d_regime == "BEAR":
        print(f"BIAS: SHORT only (daily downtrend)")
        print(f"Entry triggers (any one):")
        print(f"  - Bounce to EMA20 (~{fmt(ema(closes_1d, 20)[-1])}) and rejection")
        print(f"  - 1h RSI rises above 60 then turns down")
        print(f"  - Bollinger upper band tag with bearish close")
        print(f"Invalidation: daily close above EMA50 ({fmt(d_e50[-1])})")
    else:  # CHOP / UNKNOWN
        print(f"BIAS: NEUTRAL -- daily is in CHOP (ADX={d_adx[-1]:.1f}, threshold 20)")
        print(f"Strategy: range-trade between key levels, do NOT chase trend moves")
        print(f"  LONG if: price drops near {fmt(bbl_d[-1])} (BB lower) AND 1h RSI < 30")
        print(f"           Stop ~{fmt(bbl_d[-1] * 0.99)}, target ~{fmt(bbm_d[-1])} (BB middle)")
        print(f"  SHORT if: price rises near {fmt(bbu_d[-1])} (BB upper) AND 1h RSI > 70")
        print(f"           Stop ~{fmt(bbu_d[-1] * 1.01)}, target ~{fmt(bbm_d[-1])}")
        print(f"  WAIT if: price is in the middle. No edge there.")
        print(f"Regime change to watch:")
        print(f"  - BULL: daily close > {fmt(swing_high)} on volume = trending up")
        print(f"  - BEAR: daily close < {fmt(swing_low)} on volume = trending down")

    print(f"\nPosition size at $1000 capital, 2% risk per trade:")
    suggested_stop_dist = max(daily_atr * 0.5, last.close * 0.005)  # rough 1h-equivalent
    print(f"  ~${20:.0f} risk per trade")
    print(f"  Stop distance ~{fmt(suggested_stop_dist)} ({suggested_stop_dist/last.close*100:.2f}%)")
    print(f"  Position size ~{20/suggested_stop_dist:.4f} BTC = ~${20/suggested_stop_dist*last.close:.0f} notional")

    print(f"\n{'=' * 80}")
    print("  HONEST DISCLAIMERS")
    print(f"{'=' * 80}")
    print("  1. This is NOT a price prediction. No one can predict tomorrow's price.")
    print("  2. This is a conditional plan: 'IF price does X, THEN do Y'.")
    print("  3. Always wait for the actual trigger before entering. Don't anticipate.")
    print("  4. Even with perfect rules, expect ~40-55% of trades to lose. That's normal.")
    print("  5. Risk management > strategy choice. 2% per trade max.")
    print()


if __name__ == "__main__":
    asyncio.run(main())
