"""Stochastic Oscillator reversal.

BUY when %K crosses above %D in oversold zone (<20).
SELL when %K crosses below %D in overbought zone (>80).
A momentum-confirmation overlay on classic mean-reversion.
"""
from ..indicators import stochastic
from ..schemas import Candle, Signal
from .base import Strategy
from ._helpers import atr_array, stop_target, DEFAULT_COOLDOWN


class StochasticReversal(Strategy):
    id = "stochastic"
    name = "Stochastic Reversal"
    description = "%K crosses %D inside overbought/oversold zones."

    OVERSOLD = 20.0
    OVERBOUGHT = 80.0

    def evaluate(self, candles: list[Candle]) -> list[Signal]:
        if len(candles) < 30:
            return []
        k, d = stochastic(self.highs(candles), self.lows(candles), self.closes(candles))
        atrs = atr_array(candles)
        out: list[Signal] = []
        last_idx = -10**9
        for i in range(1, len(candles)):
            if i - last_idx < DEFAULT_COOLDOWN:
                continue
            k0, k1 = k[i - 1], k[i]
            d0, d1 = d[i - 1], d[i]
            if None in (k0, k1, d0, d1, atrs[i]):
                continue
            c = candles[i]
            if k0 <= d0 and k1 > d1 and k1 < self.OVERSOLD + 10:  # cross while still near oversold
                stop, target, _ = stop_target("BUY", c.close, atrs[i])
                out.append(Signal(
                    time=c.time, type="BUY", price=c.close,
                    reason=f"Stoch %K crossed up in oversold zone (K={k1:.1f})",
                    entry=c.close, stop_loss=stop, target=target,
                ))
                last_idx = i
            elif k0 >= d0 and k1 < d1 and k1 > self.OVERBOUGHT - 10:
                stop, target, _ = stop_target("SELL", c.close, atrs[i])
                out.append(Signal(
                    time=c.time, type="SELL", price=c.close,
                    reason=f"Stoch %K crossed down in overbought zone (K={k1:.1f})",
                    entry=c.close, stop_loss=stop, target=target,
                ))
                last_idx = i
        return out
