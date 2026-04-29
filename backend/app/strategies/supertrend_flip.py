"""SuperTrend flip strategy.

When SuperTrend's direction flips (from -1 to +1 = buy, +1 to -1 = sell), enter
in that direction. SuperTrend itself acts as a trailing-stop reference but we
use the standard ATR-based fixed stop to keep risk control comparable across
strategies.
"""
from ..indicators import supertrend
from ..schemas import Candle, Signal
from .base import Strategy
from ._helpers import atr_array, stop_target, DEFAULT_COOLDOWN


class SuperTrendFlip(Strategy):
    id = "supertrend"
    name = "SuperTrend Flip"
    description = "Enter on SuperTrend(10, 3) direction change. Tight ATR stop."

    def evaluate(self, candles: list[Candle]) -> list[Signal]:
        if len(candles) < 30:
            return []
        st, direction = supertrend(self.highs(candles), self.lows(candles), self.closes(candles), 10, 3.0)
        atrs = atr_array(candles)
        out: list[Signal] = []
        last_idx = -10**9
        for i in range(1, len(candles)):
            if i - last_idx < DEFAULT_COOLDOWN:
                continue
            d0, d1 = direction[i - 1], direction[i]
            if d0 is None or d1 is None or atrs[i] is None:
                continue
            c = candles[i]
            if d0 == -1.0 and d1 == 1.0:
                stop, target, _ = stop_target("BUY", c.close, atrs[i])
                out.append(Signal(
                    time=c.time, type="BUY", price=c.close,
                    reason="SuperTrend flipped bullish",
                    entry=c.close, stop_loss=stop, target=target,
                ))
                last_idx = i
            elif d0 == 1.0 and d1 == -1.0:
                stop, target, _ = stop_target("SELL", c.close, atrs[i])
                out.append(Signal(
                    time=c.time, type="SELL", price=c.close,
                    reason="SuperTrend flipped bearish",
                    entry=c.close, stop_loss=stop, target=target,
                ))
                last_idx = i
        return out
