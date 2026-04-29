"""High-conviction composite strategy — v2.

Fixes the wide-stop problem of v1. Stops are sized by **ATR(14)**, capped to
sane percentages of price, so they reflect *current volatility* rather than the
distant swing high/low (which is often 10-20% away on volatile assets).

Confirmation stack (all must align):
  - Trend filter:   price above EMA50 above EMA200 (or inverse for shorts)
  - Trigger:        breakout of the 20-bar range
  - Volume:         current bar >= 1.7x the 20-bar average
  - RSI sanity:     not already extended in the trade direction
  - Stop sizing:    1.5 * ATR(14), clamped to [0.4%, 2.5%] of price
  - Reward target:  2x the stop distance (2R)
  - Cooldown:       at least 8 bars between signals
"""
from __future__ import annotations

import numpy as np

from ..indicators import atr, ema, rsi
from ..schemas import Candle, Signal
from .base import Strategy


class BestTrade(Strategy):
    id = "best"
    name = "★ Best Trade (Multi-Confirmation)"
    description = (
        "Trend (EMA50/200) + 20-bar breakout + volume + RSI sanity. "
        "ATR-sized stops capped to 0.4-2.5% of price; 2R target; 8-bar cooldown."
    )

    LOOKBACK = 20
    EMA_SHORT = 50
    EMA_LONG = 200
    VOL_MULT = 1.7
    REWARD_R = 2.0
    COOLDOWN_BARS = 8

    RSI_PERIOD = 14
    RSI_LONG_MAX = 72.0
    RSI_SHORT_MIN = 28.0

    ATR_PERIOD = 14
    ATR_MULT = 1.5
    STOP_PCT_MIN = 0.004   # 0.4% of price — never tighter than this
    STOP_PCT_MAX = 0.025   # 2.5% of price — never wider than this

    def evaluate(self, candles: list[Candle]) -> list[Signal]:
        need = max(self.EMA_LONG, self.ATR_PERIOD) + self.LOOKBACK + 2
        if len(candles) < need:
            return []

        closes = self.closes(candles)
        highs = self.highs(candles)
        lows = self.lows(candles)
        vols = self.volumes(candles)
        e50 = ema(closes, self.EMA_SHORT)
        e200 = ema(closes, self.EMA_LONG)
        r = rsi(closes, self.RSI_PERIOD)
        a = atr(highs, lows, closes, self.ATR_PERIOD)

        out: list[Signal] = []
        last_signal_idx = -10**9

        start = max(self.EMA_LONG, self.ATR_PERIOD) + self.LOOKBACK
        for i in range(start, len(candles)):
            if i - last_signal_idx < self.COOLDOWN_BARS:
                continue
            c = candles[i]
            m, l, ri, av = e50[i], e200[i], r[i], a[i]
            if None in (m, l, ri, av):
                continue

            window_h = float(np.max(highs[i - self.LOOKBACK:i]))
            window_l = float(np.min(lows[i - self.LOOKBACK:i]))
            avg_vol = float(np.mean(vols[i - self.LOOKBACK:i]))
            if avg_vol == 0:
                continue

            uptrend = c.close > m > l
            downtrend = c.close < m < l
            vol_ok = c.volume >= avg_vol * self.VOL_MULT

            # ATR-based stop distance, clamped to a percent-of-price band.
            stop_dist = av * self.ATR_MULT
            stop_dist = max(stop_dist, c.close * self.STOP_PCT_MIN)
            stop_dist = min(stop_dist, c.close * self.STOP_PCT_MAX)
            target_dist = stop_dist * self.REWARD_R

            if uptrend and c.close > window_h and vol_ok and ri < self.RSI_LONG_MAX:
                stop = c.close - stop_dist
                target = c.close + target_dist
                out.append(Signal(
                    time=c.time, type="BUY", price=c.close,
                    reason=(
                        f"Uptrend + breakout above {window_h:.2f} on {c.volume / avg_vol:.1f}× vol  "
                        f"(stop -{stop_dist / c.close * 100:.2f}%, target +{target_dist / c.close * 100:.2f}%, RR=2.0)"
                    ),
                    entry=c.close, stop_loss=stop, target=target,
                ))
                last_signal_idx = i

            elif downtrend and c.close < window_l and vol_ok and ri > self.RSI_SHORT_MIN:
                stop = c.close + stop_dist
                target = c.close - target_dist
                out.append(Signal(
                    time=c.time, type="SELL", price=c.close,
                    reason=(
                        f"Downtrend + breakdown below {window_l:.2f} on {c.volume / avg_vol:.1f}× vol  "
                        f"(stop +{stop_dist / c.close * 100:.2f}%, target -{target_dist / c.close * 100:.2f}%, RR=2.0)"
                    ),
                    entry=c.close, stop_loss=stop, target=target,
                ))
                last_signal_idx = i

        return out
