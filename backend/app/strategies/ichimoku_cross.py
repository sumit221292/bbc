"""Ichimoku Cloud — Tenkan/Kijun cross with cloud filter.

BUY when:
  - Tenkan (conversion) crosses above Kijun (base), AND
  - Price is above the cloud (above max(span A, span B))
SELL on the inverse.
"""
from ..indicators import ichimoku
from ..schemas import Candle, Signal
from .base import Strategy
from ._helpers import atr_array, stop_target, DEFAULT_COOLDOWN


class IchimokuCross(Strategy):
    id = "ichimoku"
    name = "Ichimoku Cloud Cross"
    description = "Tenkan/Kijun cross filtered by price vs cloud."

    def evaluate(self, candles: list[Candle]) -> list[Signal]:
        if len(candles) < 60:
            return []
        tenkan, kijun, span_a, span_b = ichimoku(self.highs(candles), self.lows(candles), self.closes(candles))
        atrs = atr_array(candles)
        out: list[Signal] = []
        last_idx = -10**9
        for i in range(1, len(candles)):
            if i - last_idx < DEFAULT_COOLDOWN:
                continue
            t0, t1 = tenkan[i - 1], tenkan[i]
            k0, k1 = kijun[i - 1], kijun[i]
            sa, sb = span_a[i], span_b[i]
            if None in (t0, t1, k0, k1, sa, sb, atrs[i]):
                continue
            cloud_top = max(sa, sb)
            cloud_bot = min(sa, sb)
            c = candles[i]
            if t0 <= k0 and t1 > k1 and c.close > cloud_top:
                stop, target, _ = stop_target("BUY", c.close, atrs[i])
                out.append(Signal(
                    time=c.time, type="BUY", price=c.close,
                    reason="Tenkan crossed above Kijun, price above cloud",
                    entry=c.close, stop_loss=stop, target=target,
                ))
                last_idx = i
            elif t0 >= k0 and t1 < k1 and c.close < cloud_bot:
                stop, target, _ = stop_target("SELL", c.close, atrs[i])
                out.append(Signal(
                    time=c.time, type="SELL", price=c.close,
                    reason="Tenkan crossed below Kijun, price below cloud",
                    entry=c.close, stop_loss=stop, target=target,
                ))
                last_idx = i
        return out
