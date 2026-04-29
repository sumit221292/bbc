"""Multi-Timeframe analysis engine.

Real-trader logic: align decisions across 3 timeframes so we never take a
counter-trend trade by accident.

  1d (daily)  -> regime detection: BULL / BEAR / CHOP
  4h          -> direction confirmation
  1h          -> entry trigger (pullback / mean reversion within the trend)

We carefully avoid lookahead bias: at any 1h bar at time t, we only consult
the most recent 1d / 4h bars that have **fully closed** by time t.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from typing import Literal

from .indicators import adx, atr, bollinger, ema, rsi
from .schemas import Candle, Signal


Regime = Literal["BULL", "BEAR", "CHOP", "UNKNOWN"]

INTERVAL_SECONDS = {"1h": 3600, "4h": 14400, "1d": 86400}


def _last_closed_idx(times: list[int], t: int, interval_sec: int) -> int:
    """Index of the most recent bar that has fully closed by time `t`."""
    cutoff = t - interval_sec
    return bisect_right(times, cutoff) - 1


@dataclass
class MTFContext:
    candles_1h: list[Candle]
    candles_4h: list[Candle]
    candles_1d: list[Candle]

    def __post_init__(self):
        self._compute()

    def _compute(self):
        c1d = [c.close for c in self.candles_1d]
        h1d = [c.high for c in self.candles_1d]
        l1d = [c.low for c in self.candles_1d]
        self.d_ema50 = ema(c1d, 50)
        self.d_ema200 = ema(c1d, 200)
        self.d_adx, _, _ = adx(h1d, l1d, c1d, 14)
        self.d_times = [c.time for c in self.candles_1d]

        c4h = [c.close for c in self.candles_4h]
        self.h4_ema50 = ema(c4h, 50)
        self.h4_ema200 = ema(c4h, 200)
        self.h4_times = [c.time for c in self.candles_4h]

        c1h = [c.close for c in self.candles_1h]
        h1h = [c.high for c in self.candles_1h]
        l1h = [c.low for c in self.candles_1h]
        self.h1_ema20 = ema(c1h, 20)
        self.h1_ema50 = ema(c1h, 50)
        self.h1_rsi = rsi(c1h, 14)
        self.h1_atr = atr(h1h, l1h, c1h, 14)
        self.h1_bbu, self.h1_bbm, self.h1_bbl = bollinger(c1h, 20, 2.0)

    # ---- regime helpers ----
    def daily_regime_at(self, t: int, adx_min: float = 20.0) -> Regime:
        idx = _last_closed_idx(self.d_times, t, INTERVAL_SECONDS["1d"])
        if idx < 0:
            return "UNKNOWN"
        e50, e200, adx_v = self.d_ema50[idx], self.d_ema200[idx], self.d_adx[idx]
        if None in (e50, e200, adx_v):
            return "UNKNOWN"
        last_close = self.candles_1d[idx].close
        if adx_v >= adx_min:
            if last_close > e50 > e200:
                return "BULL"
            if last_close < e50 < e200:
                return "BEAR"
        return "CHOP"

    def h4_regime_at(self, t: int) -> Regime:
        idx = _last_closed_idx(self.h4_times, t, INTERVAL_SECONDS["4h"])
        if idx < 0:
            return "UNKNOWN"
        e50, e200 = self.h4_ema50[idx], self.h4_ema200[idx]
        if e50 is None:
            return "UNKNOWN"
        last_close = self.candles_4h[idx].close
        # Soft confirmation: above EMA50 = BULL bias, below = BEAR bias.
        # We don't require EMA50 > EMA200 here — that would be redundant with 1d.
        return "BULL" if last_close > e50 else "BEAR"


# ---------------------------------------------------------------------------
# Strategy variants
# ---------------------------------------------------------------------------

COOLDOWN_BARS = 6
ATR_MULT = 1.5
STOP_PCT_MIN = 0.004
STOP_PCT_MAX = 0.025
REWARD_R = 2.0


def _make_signal(c: Candle, side: str, atr_v: float, reason: str) -> Signal:
    dist = max(atr_v * ATR_MULT, c.close * STOP_PCT_MIN)
    dist = min(dist, c.close * STOP_PCT_MAX)
    if side == "BUY":
        stop = c.close - dist
        target = c.close + dist * REWARD_R
    else:
        stop = c.close + dist
        target = c.close - dist * REWARD_R
    return Signal(
        time=c.time, type=side, price=c.close, reason=reason,
        entry=c.close, stop_loss=stop, target=target,
    )


def evaluate_strict(ctx: MTFContext, start_idx: int = 0) -> list[Signal]:
    """3-screen strict: 1d regime + 4h confirmation + 1h trigger. Most selective."""
    return _evaluate(ctx, start_idx, require_4h=True, allow_chop=False, adx_min=20.0)


def evaluate_2screen(ctx: MTFContext, start_idx: int = 0) -> list[Signal]:
    """2-screen: 1d regime + 1h trigger (4h ignored)."""
    return _evaluate(ctx, start_idx, require_4h=False, allow_chop=False, adx_min=20.0)


def evaluate_relaxed(ctx: MTFContext, start_idx: int = 0) -> list[Signal]:
    """Lower the ADX bar so we catch weaker trends too."""
    return _evaluate(ctx, start_idx, require_4h=False, allow_chop=False, adx_min=15.0)


def evaluate_chop_aware(ctx: MTFContext, start_idx: int = 0) -> list[Signal]:
    """In trends -> trend continuation. In chop -> mean reversion (RSI-confirmed)."""
    return _evaluate(ctx, start_idx, require_4h=False, allow_chop=True, adx_min=20.0)


def evaluate_chop_only(ctx: MTFContext, start_idx: int = 0) -> list[Signal]:
    """Trade ONLY in chop regimes — pure mean reversion, no trend trades."""
    return _evaluate(ctx, start_idx, require_4h=False, allow_chop=True,
                     adx_min=20.0, chop_only=True)


def _evaluate(ctx: MTFContext, start_idx: int, require_4h: bool, allow_chop: bool,
              adx_min: float = 20.0, chop_only: bool = False) -> list[Signal]:
    out: list[Signal] = []
    last_sig_idx = -10**9

    for i in range(max(50, start_idx), len(ctx.candles_1h)):
        if i - last_sig_idx < COOLDOWN_BARS:
            continue

        c = ctx.candles_1h[i]
        prev = ctx.candles_1h[i - 1]

        e20, e50 = ctx.h1_ema20[i], ctx.h1_ema50[i]
        rsi_v, rsi_p = ctx.h1_rsi[i], ctx.h1_rsi[i - 1]
        atr_v = ctx.h1_atr[i]
        bbu, bbl = ctx.h1_bbu[i], ctx.h1_bbl[i]
        bbu_p, bbl_p = ctx.h1_bbu[i - 1], ctx.h1_bbl[i - 1]
        if None in (e20, e50, rsi_v, rsi_p, atr_v, bbu, bbl, bbu_p, bbl_p):
            continue

        d_reg = ctx.daily_regime_at(c.time, adx_min=adx_min)
        h4_reg = ctx.h4_regime_at(c.time)

        # ---- chop branch (mean reversion when allowed) ----
        # Stronger filter: BB tag AND RSI extreme on the prior bar.
        if d_reg == "CHOP" and allow_chop:
            if prev.close < bbl_p and c.close > bbl and rsi_p < 30:
                out.append(_make_signal(c, "BUY", atr_v,
                                        f"CHOP: BB lower + RSI {rsi_p:.0f} reversion"))
                last_sig_idx = i
            elif prev.close > bbu_p and c.close < bbu and rsi_p > 70:
                out.append(_make_signal(c, "SELL", atr_v,
                                        f"CHOP: BB upper + RSI {rsi_p:.0f} reversion"))
                last_sig_idx = i
            continue

        if chop_only:
            continue
        if d_reg in ("CHOP", "UNKNOWN"):
            continue
        if require_4h and h4_reg != d_reg:
            continue

        # ---- trending branches (pullback continuation) ----
        if d_reg == "BULL":
            trigger, reason = False, ""
            # Trigger 1: RSI pullback bounce
            if rsi_p < 40 and rsi_v > rsi_p:
                trigger = True
                reason = f"BULL+pullback: RSI bounce from {rsi_p:.1f}"
            # Trigger 2: Lower BB tag
            elif prev.low <= bbl_p and c.close > prev.close:
                trigger = True
                reason = "BULL+pullback: lower-BB bounce"
            # Trigger 3: EMA20 retest hold
            elif prev.low <= e20 and c.close > e20 and c.close > prev.close:
                trigger = True
                reason = "BULL+pullback: EMA20 retest hold"

            if trigger:
                out.append(_make_signal(c, "BUY", atr_v, reason))
                last_sig_idx = i

        elif d_reg == "BEAR":
            trigger, reason = False, ""
            if rsi_p > 60 and rsi_v < rsi_p:
                trigger = True
                reason = f"BEAR+pullback: RSI roll from {rsi_p:.1f}"
            elif prev.high >= bbu_p and c.close < prev.close:
                trigger = True
                reason = "BEAR+pullback: upper-BB rejection"
            elif prev.high >= e20 and c.close < e20 and c.close < prev.close:
                trigger = True
                reason = "BEAR+pullback: EMA20 retest fail"

            if trigger:
                out.append(_make_signal(c, "SELL", atr_v, reason))
                last_sig_idx = i

    return out
