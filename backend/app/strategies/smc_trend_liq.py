"""SMC Trend + Liquidity Combo — port of the Pine Script v2 strategy.

Logic mirrors the user's Pine source:
  1. HTF (4h) EMA50 trend bias
  2. Real pivot-high / pivot-low detection (5 bars left + right)
  3. Liquidity sweep over the prior 20 bars (wick + reclaim)
  4. Break of Structure: close beyond the last confirmed pivot
  5. Entry only when ALL three align (trend + sweep + BOS) within the
     sweep validity window (5 bars)
  6. SL = lowest_20 / highest_20 ± a small price-tick padding
  7. TP = entry ± risk × RR (default 1:4)

Runs on 1h candles using the existing MTFContext (which already fetches
1h + 4h + 1d). The 4h candles drive the trend bias.
"""
from __future__ import annotations

from bisect import bisect_right

from ..multi_tf import INTERVAL_SECONDS, MTFContext
from ..schemas import Candle, Signal


# Tunables (mirrored from the Pine script defaults)
EMA_LEN = 50
PIVOT_LEN = 5            # ta.pivothigh / pivotlow lookback both sides
LOOKBACK = 20            # liquidity / SL window
SWEEP_WINDOW = 5         # bars allowed between sweep and BOS
RR = 4.0                 # 1:4 risk:reward
SL_PADDING = 0.10        # 10 BTC ticks (~$0.10) — tiny buffer
COOLDOWN_BARS = 6        # don't fire back-to-back signals


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
    """Index of the latest 4h bar that has fully closed by time t."""
    cutoff = t - INTERVAL_SECONDS["4h"]
    return bisect_right(h4_times, cutoff) - 1


def evaluate_smc_trend_liq(ctx: MTFContext, start_idx: int = 0) -> list[Signal]:
    c1h = ctx.candles_1h
    h4_times = ctx.h4_times
    h4_ema50 = ctx.h4_ema50  # already computed in MTFContext

    out: list[Signal] = []
    last_ph: float | None = None
    last_pl: float | None = None
    sweep_low_bar = -10**9
    sweep_high_bar = -10**9
    last_sig_idx = -10**9

    start = max(start_idx, LOOKBACK + PIVOT_LEN)
    for i in range(start, len(c1h)):
        if i - last_sig_idx < COOLDOWN_BARS:
            continue
        c = c1h[i]

        # --- HTF (4h) trend bias ---
        h4_idx = _h4_idx_for(h4_times, c.time)
        if h4_idx < 0:
            continue
        h4_ema = h4_ema50[h4_idx]
        if h4_ema is None:
            continue
        uptrend = c.close > h4_ema
        downtrend = c.close < h4_ema

        # --- Pivot confirmation (with PIVOT_LEN-bar lookahead, no future bias) ---
        confirm_idx = i - PIVOT_LEN
        if confirm_idx >= PIVOT_LEN:
            if _is_swing_high(c1h, confirm_idx, PIVOT_LEN):
                last_ph = c1h[confirm_idx].high
            if _is_swing_low(c1h, confirm_idx, PIVOT_LEN):
                last_pl = c1h[confirm_idx].low

        # --- Liquidity sweep over prior 20 bars (excluding current) ---
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

        # --- Entry: trend + sweep + BOS all aligned ---
        if uptrend and sweep_buy_active and bos_buy:
            sl = prior_low - SL_PADDING
            tp = c.close + (c.close - sl) * RR
            out.append(Signal(
                time=c.time, type="BUY", price=c.close,
                reason=(
                    f"SMC Trend+Liq BUY: 4h uptrend (>{h4_ema:.0f}), "
                    f"swept ${prior_low:.0f}, BOS ${last_ph:.0f}, RR=1:{RR:.0f}"
                ),
                entry=c.close, stop_loss=sl, target=tp,
            ))
            sweep_low_bar = -10**9  # reset so we don't re-fire on the same sweep
            last_sig_idx = i
        elif downtrend and sweep_sell_active and bos_sell:
            sl = prior_high + SL_PADDING
            tp = c.close - (sl - c.close) * RR
            out.append(Signal(
                time=c.time, type="SELL", price=c.close,
                reason=(
                    f"SMC Trend+Liq SELL: 4h downtrend (<{h4_ema:.0f}), "
                    f"swept ${prior_high:.0f}, BOS ${last_pl:.0f}, RR=1:{RR:.0f}"
                ),
                entry=c.close, stop_loss=sl, target=tp,
            ))
            sweep_high_bar = -10**9
            last_sig_idx = i

    return out
