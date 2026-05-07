"""SMC Trend + Liquidity Combo — Pine v2 port, regime-filtered.

Tuning history (in commit messages):
  v1: Pine defaults  (4 signals, too rare to evaluate)
  v2: + continuation (64 signals, 25% WR, breakeven)
  v3: continuation + pullback (31 signals, 13.8% WR, worse)
  v4: drop continuation (14 signals, 15.4% WR, still bad in chop)
  v5 (current):
      + 4h ADX > 20 filter (only trade in real trends)
      + ATR-based SL with floor (more breathing room than wick stops)
      + RR 1:3 -> 1:2 (matches global filter; achievable targets)

Lesson: SMC trend+sweep is a TRENDING-MARKET strategy. In chop the sweep
often happens AT the top/bottom and reverses. The ADX filter ensures we
only fire when there's a real directional move on the 4h timeframe.
"""
from __future__ import annotations

from bisect import bisect_right

from ..indicators import atr
from ..multi_tf import INTERVAL_SECONDS, MTFContext
from ..schemas import Candle, Signal


EMA_LEN = 50
PIVOT_LEN = 3
LOOKBACK = 15
SWEEP_WINDOW = 12
RR = 2.0                  # 1:2 (matches global RR floor)
COOLDOWN_BARS = 4

# ADX(14) on 4h must clear this to confirm a real trending regime.
ADX_4H_MIN = 20.0

# ATR-based SL is more forgiving than a wick-based stop. The actual SL is
# max(swing-based stop, ATR×1.5 stop) to keep enough room.
ATR_PERIOD = 14
ATR_MULT = 1.5


def _is_swing_high(candles: list[Candle], i: int, n: int) -> bool:
    if i < n or i >= len(candles) - n:
        return False
    h = candles[i].high
    for j in range(i - n, i + n + 1):
        if j == i:
            continue
        if candles[j].high >= h:
            return False
    return True


def _is_swing_low(candles: list[Candle], i: int, n: int) -> bool:
    if i < n or i >= len(candles) - n:
        return False
    l = candles[i].low
    for j in range(i - n, i + n + 1):
        if j == i:
            continue
        if candles[j].low <= l:
            return False
    return True


def _h4_idx_for(h4_times: list[int], t: int) -> int:
    cutoff = t - INTERVAL_SECONDS["4h"]
    return bisect_right(h4_times, cutoff) - 1


def evaluate_smc_trend_liq(ctx: MTFContext, start_idx: int = 0) -> list[Signal]:
    c1h = ctx.candles_1h
    c4h = ctx.candles_4h
    h4_times = ctx.h4_times
    h4_ema50 = ctx.h4_ema50

    # 4h ADX for the regime filter.
    from ..indicators import adx as adx_fn
    h4_adx, _, _ = adx_fn(
        [c.high for c in c4h], [c.low for c in c4h], [c.close for c in c4h], 14,
    )

    # 1h ATR for stop sizing.
    h1_atr = atr(
        [c.high for c in c1h], [c.low for c in c1h], [c.close for c in c1h], ATR_PERIOD,
    )

    out: list[Signal] = []
    last_ph: float | None = None
    last_pl: float | None = None
    sweep_low_bar = -10**9
    sweep_high_bar = -10**9
    last_sig_idx = -10**9

    start = max(start_idx, LOOKBACK + PIVOT_LEN, ATR_PERIOD + 1)
    for i in range(start, len(c1h)):
        c = c1h[i]

        # --- HTF (4h) trend bias + ADX regime filter ---
        h4_idx = _h4_idx_for(h4_times, c.time)
        if h4_idx < 0:
            continue
        h4_ema = h4_ema50[h4_idx]
        h4_adx_v = h4_adx[h4_idx] if h4_idx < len(h4_adx) else None
        if h4_ema is None or h4_adx_v is None or h4_adx_v < ADX_4H_MIN:
            continue
        uptrend = c.close > h4_ema
        downtrend = c.close < h4_ema

        # --- Pivot confirmation ---
        confirm_idx = i - PIVOT_LEN
        if confirm_idx >= PIVOT_LEN:
            if _is_swing_high(c1h, confirm_idx, PIVOT_LEN):
                last_ph = c1h[confirm_idx].high
            if _is_swing_low(c1h, confirm_idx, PIVOT_LEN):
                last_pl = c1h[confirm_idx].low

        # --- Liquidity sweep detection ---
        prior_window = c1h[i - LOOKBACK: i]
        prior_high = max(k.high for k in prior_window)
        prior_low = min(k.low for k in prior_window)

        if c.low < prior_low and c.close > prior_low:
            sweep_low_bar = i
        if c.high > prior_high and c.close < prior_high:
            sweep_high_bar = i

        sweep_buy_active = (i - sweep_low_bar) <= SWEEP_WINDOW
        sweep_sell_active = (i - sweep_high_bar) <= SWEEP_WINDOW

        # --- Break of Structure ---
        bos_buy = last_ph is not None and c.close > last_ph
        bos_sell = last_pl is not None and c.close < last_pl

        if i - last_sig_idx < COOLDOWN_BARS:
            continue

        # --- Stop sizing: max of (swing-based, ATR-based) for breathing room ---
        atr_v = h1_atr[i]
        if atr_v is None:
            continue
        atr_stop_dist = atr_v * ATR_MULT

        if uptrend and sweep_buy_active and bos_buy:
            swing_sl = prior_low
            atr_sl = c.close - atr_stop_dist
            sl = min(swing_sl, atr_sl)   # whichever is further from entry
            tp = c.close + (c.close - sl) * RR
            out.append(Signal(
                time=c.time, type="BUY", price=c.close,
                reason=(
                    f"SMC Trend+Liq BUY: 4h>${h4_ema:.0f} ADX={h4_adx_v:.0f}, "
                    f"swept ${prior_low:.0f}, BOS>${last_ph:.0f}, RR=1:{RR:.0f}"
                ),
                entry=c.close, stop_loss=sl, target=tp,
            ))
            sweep_low_bar = -10**9
            last_sig_idx = i
        elif downtrend and sweep_sell_active and bos_sell:
            swing_sl = prior_high
            atr_sl = c.close + atr_stop_dist
            sl = max(swing_sl, atr_sl)
            tp = c.close - (sl - c.close) * RR
            out.append(Signal(
                time=c.time, type="SELL", price=c.close,
                reason=(
                    f"SMC Trend+Liq SELL: 4h<${h4_ema:.0f} ADX={h4_adx_v:.0f}, "
                    f"swept ${prior_high:.0f}, BOS<${last_pl:.0f}, RR=1:{RR:.0f}"
                ),
                entry=c.close, stop_loss=sl, target=tp,
            ))
            sweep_high_bar = -10**9
            last_sig_idx = i

    return out
