"""★★★ Champion — adaptive regime-switching strategy.

Combines the most reliable patterns from across the suite:
  STRONG TREND  (1d ADX > 25) -> pullback continuation (Best Trade idea)
  MILD TREND    (15-25)       -> breakout multi-confirmation
  PURE CHOP     (< 15)        -> Bollinger + RSI extreme reversion

Universal filters across all regimes:
  - Volume >= 0.5x rolling avg (skip dead bars)
  - ATR >= 0.3% of price (skip illiquid periods)
  - ATR-based stop, capped 0.5-2.5% of price
  - 2R minimum target (matches the 1:2 RR floor)
  - 6-bar cooldown between signals
"""
from __future__ import annotations

import numpy as np

from ..indicators import adx, atr, bollinger, ema, rsi
from ..schemas import Candle, Signal
from .base import Strategy


class Champion(Strategy):
    id = "champion"
    name = "★★★ Champion (Adaptive Regime)"
    description = (
        "Regime-adaptive: trend pullbacks in strong trends, breakout "
        "multi-confirmation in mild trends, BB+RSI reversion in chop. "
        "Best blend of the suite's working ideas. Designed for 1h or 4h."
    )
    # Backtest +0.27pp with trail. Regime-adaptive nature means follow-up
    # signals usually confirm the current regime; ratchet is safe.
    supports_trail = True

    LOOKBACK = 20
    EMA_SHORT = 20
    EMA_MID = 50
    EMA_LONG = 200
    RSI_PERIOD = 14
    ATR_PERIOD = 14
    ADX_PERIOD = 14

    # Regime thresholds
    # v5: STRONG raised to 30 because ADX 25-30 wasn't strong enough — pullback
    # entries kept getting reversed. True power trends only above 30.
    ADX_STRONG = 30.0
    ADX_MILD = 15.0

    # Risk — v10: tightened SL after empirical sweep (best avg PnL).
    # Sweep test: ATR_MULT 1.5/1.2/1.0/0.8/0.5 -> 1.0 won decisively.
    # Going tighter (0.8, 0.5) hurt because normal noise hits the stop.
    ATR_MULT = 1.0
    STOP_PCT_MIN = 0.003
    STOP_PCT_MAX = 0.015
    REWARD_R_STRONG = 2.5     # strong trend: amplify continuation
    REWARD_R_MILD = 2.0       # mild trend: capture short bursts
    REWARD_R_CHOP = 2.0       # chop: BB-middle target
    COOLDOWN_BARS = 6

    # Quality gates
    MIN_VOL_MULT = 0.5      # need at least 50% of avg volume
    MIN_ATR_PCT = 0.003     # need at least 0.3% volatility

    # Strong-trend pullback parameters
    PULLBACK_LOOKBACK = 5
    PULLBACK_RSI_BUY_MAX = 45
    PULLBACK_RSI_SELL_MIN = 55

    # Mild-trend breakout parameters.
    # v3: kept v1 vol/RSI thresholds (which worked on 4h) but added a
    # small margin requirement on the breakout close so marginal 1h
    # fakeouts get filtered.
    BREAKOUT_VOL_MULT = 1.7
    BREAKOUT_RSI_LONG_MAX = 70
    BREAKOUT_RSI_SHORT_MIN = 30
    BREAKOUT_MARGIN_PCT = 0.0015   # close must be 0.15% above the window high

    # Chop reversion parameters
    CHOP_RSI_OVERSOLD = 30
    CHOP_RSI_OVERBOUGHT = 70

    def evaluate(self, candles: list[Candle]) -> list[Signal]:
        if len(candles) < 220:
            return []

        closes = self.closes(candles)
        highs = self.highs(candles)
        lows = self.lows(candles)
        vols = self.volumes(candles)

        e20 = ema(closes, self.EMA_SHORT)
        e50 = ema(closes, self.EMA_MID)
        e200 = ema(closes, self.EMA_LONG)
        r = rsi(closes, self.RSI_PERIOD)
        a = atr(highs, lows, closes, self.ATR_PERIOD)
        adx_v, _, _ = adx(highs, lows, closes, self.ADX_PERIOD)
        bbu, bbm, bbl = bollinger(closes, 20, 2.0)

        out: list[Signal] = []
        last_sig_idx = -10**9

        for i in range(220, len(candles)):
            if i - last_sig_idx < self.COOLDOWN_BARS:
                continue

            c = candles[i]
            need = (e20[i], e50[i], e200[i], r[i], a[i], adx_v[i],
                    bbu[i], bbm[i], bbl[i])
            if any(x is None for x in need):
                continue

            # --- Universal quality gates ---
            avg_vol = float(np.mean(vols[i - self.LOOKBACK:i]))
            if avg_vol == 0 or c.volume < avg_vol * self.MIN_VOL_MULT:
                continue
            atr_pct = a[i] / c.close
            if atr_pct < self.MIN_ATR_PCT:
                continue

            # --- ATR-based risk sizing ---
            stop_dist = a[i] * self.ATR_MULT
            stop_dist = max(stop_dist, c.close * self.STOP_PCT_MIN)
            stop_dist = min(stop_dist, c.close * self.STOP_PCT_MAX)
            # target_dist is set per-regime below

            # --- Regime classification ---
            adx_now = adx_v[i]
            ema50_above_200 = e50[i] > e200[i]
            ema50_below_200 = e50[i] < e200[i]

            bull_strong = c.close > e50[i] and ema50_above_200 and adx_now > self.ADX_STRONG
            bear_strong = c.close < e50[i] and ema50_below_200 and adx_now > self.ADX_STRONG
            # v4: MILD branches now also require macro EMA50/200 alignment.
            # Without it, "mild trend" up while EMA50<EMA200 is just a bear
            # rally — breakouts there fail (this killed PnL on 1h).
            bull_mild = (c.close > e50[i] and ema50_above_200
                         and self.ADX_MILD < adx_now <= self.ADX_STRONG)
            bear_mild = (c.close < e50[i] and ema50_below_200
                         and self.ADX_MILD < adx_now <= self.ADX_STRONG)
            chop = adx_now <= self.ADX_MILD

            window = candles[i - self.LOOKBACK:i]
            window_high = max(k.high for k in window)
            window_low = min(k.low for k in window)

            # === REGIME 1: STRONG TREND — pullback continuation ===
            if bull_strong:
                pullback = any(
                    candles[j].low <= e20[j]
                    for j in range(max(0, i - self.PULLBACK_LOOKBACK), i + 1)
                    if e20[j] is not None
                )
                rsi_p = r[i - 1]
                rsi_bounce = (rsi_p is not None
                              and rsi_p < self.PULLBACK_RSI_BUY_MAX
                              and r[i] > rsi_p)
                if pullback and rsi_bounce:
                    target_dist = stop_dist * self.REWARD_R_STRONG
                    out.append(Signal(
                        time=c.time, type="BUY", price=c.close,
                        reason=(
                            f"Champion BULL_TREND (ADX={adx_now:.0f}, RR=1:{self.REWARD_R_STRONG:.0f}): "
                            f"pullback to EMA20 + RSI bounce ({rsi_p:.0f}->{r[i]:.0f})"
                        ),
                        entry=c.close,
                        stop_loss=c.close - stop_dist,
                        target=c.close + target_dist,
                    ))
                    last_sig_idx = i
                    continue

            elif bear_strong:
                rejection = any(
                    candles[j].high >= e20[j]
                    for j in range(max(0, i - self.PULLBACK_LOOKBACK), i + 1)
                    if e20[j] is not None
                )
                rsi_p = r[i - 1]
                rsi_roll = (rsi_p is not None
                            and rsi_p > self.PULLBACK_RSI_SELL_MIN
                            and r[i] < rsi_p)
                if rejection and rsi_roll:
                    target_dist = stop_dist * self.REWARD_R_STRONG
                    out.append(Signal(
                        time=c.time, type="SELL", price=c.close,
                        reason=(
                            f"Champion BEAR_TREND (ADX={adx_now:.0f}, RR=1:{self.REWARD_R_STRONG:.0f}): "
                            f"rally to EMA20 + RSI roll ({rsi_p:.0f}->{r[i]:.0f})"
                        ),
                        entry=c.close,
                        stop_loss=c.close + stop_dist,
                        target=c.close - target_dist,
                    ))
                    last_sig_idx = i
                    continue

            # === REGIME 2: MILD TREND — breakout multi-confirmation ===
            if bull_mild:
                if (c.close > window_high * (1 + self.BREAKOUT_MARGIN_PCT)
                        and c.volume >= avg_vol * self.BREAKOUT_VOL_MULT
                        and r[i] < self.BREAKOUT_RSI_LONG_MAX):
                    target_dist = stop_dist * self.REWARD_R_MILD
                    out.append(Signal(
                        time=c.time, type="BUY", price=c.close,
                        reason=(
                            f"Champion BULL_MILD (ADX={adx_now:.0f}, RR=1:{self.REWARD_R_MILD:.0f}): "
                            f"breakout {window_high:.0f} on "
                            f"{c.volume / avg_vol:.1f}x vol"
                        ),
                        entry=c.close,
                        stop_loss=c.close - stop_dist,
                        target=c.close + target_dist,
                    ))
                    last_sig_idx = i
                    continue

            elif bear_mild:
                if (c.close < window_low * (1 - self.BREAKOUT_MARGIN_PCT)
                        and c.volume >= avg_vol * self.BREAKOUT_VOL_MULT
                        and r[i] > self.BREAKOUT_RSI_SHORT_MIN):
                    target_dist = stop_dist * self.REWARD_R_MILD
                    out.append(Signal(
                        time=c.time, type="SELL", price=c.close,
                        reason=(
                            f"Champion BEAR_MILD (ADX={adx_now:.0f}, RR=1:{self.REWARD_R_MILD:.0f}): "
                            f"breakdown {window_low:.0f} on "
                            f"{c.volume / avg_vol:.1f}x vol"
                        ),
                        entry=c.close,
                        stop_loss=c.close + stop_dist,
                        target=c.close - target_dist,
                    ))
                    last_sig_idx = i
                    continue

            # === REGIME 3: PURE CHOP — BB + RSI extreme reversion ===
            if chop:
                prev = candles[i - 1]
                rsi_p = r[i - 1]
                if (prev.close <= bbl[i - 1]
                        and c.close > bbl[i]
                        and rsi_p is not None
                        and rsi_p < self.CHOP_RSI_OVERSOLD):
                    # Target = BB middle, but enforce regime RR floor
                    target_dist = stop_dist * self.REWARD_R_CHOP
                    target = max(bbm[i], c.close + target_dist)
                    out.append(Signal(
                        time=c.time, type="BUY", price=c.close,
                        reason=(
                            f"Champion CHOP (ADX={adx_now:.0f}): "
                            f"BB lower + RSI {rsi_p:.0f} reversion"
                        ),
                        entry=c.close,
                        stop_loss=c.close - stop_dist,
                        target=target,
                    ))
                    last_sig_idx = i
                elif (prev.close >= bbu[i - 1]
                        and c.close < bbu[i]
                        and rsi_p is not None
                        and rsi_p > self.CHOP_RSI_OVERBOUGHT):
                    target_dist = stop_dist * self.REWARD_R_CHOP
                    target = min(bbm[i], c.close - target_dist)
                    out.append(Signal(
                        time=c.time, type="SELL", price=c.close,
                        reason=(
                            f"Champion CHOP (ADX={adx_now:.0f}): "
                            f"BB upper + RSI {rsi_p:.0f} reversion"
                        ),
                        entry=c.close,
                        stop_loss=c.close + stop_dist,
                        target=target,
                    ))
                    last_sig_idx = i

        return out
