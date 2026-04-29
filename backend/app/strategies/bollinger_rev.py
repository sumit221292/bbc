"""Bollinger Band mean reversion.

BUY when price closes below the lower band then closes back inside (bear-trap).
SELL when price closes above the upper band then closes back inside (bull-trap).
Works best in range-bound markets.
"""
from ..indicators import bollinger
from ..schemas import Candle, Signal
from .base import Strategy
from ._helpers import atr_array, stop_target, DEFAULT_COOLDOWN


class BollingerReversion(Strategy):
    id = "bollinger"
    name = "Bollinger Band Reversion"
    description = "Mean-revert when price pokes outside the bands then closes back inside."

    def evaluate(self, candles: list[Candle]) -> list[Signal]:
        if len(candles) < 30:
            return []
        closes = self.closes(candles)
        upper, middle, lower = bollinger(closes, 20, 2.0)
        atrs = atr_array(candles)
        out: list[Signal] = []
        last_idx = -10**9
        for i in range(1, len(candles)):
            if i - last_idx < DEFAULT_COOLDOWN:
                continue
            if None in (upper[i], lower[i], upper[i - 1], lower[i - 1], atrs[i]):
                continue
            c = candles[i]
            prev = candles[i - 1]
            # Buy: previous bar closed below lower band, current bar closes back inside.
            if prev.close < lower[i - 1] and c.close > lower[i]:
                stop, target, _ = stop_target("BUY", c.close, atrs[i])
                out.append(Signal(
                    time=c.time, type="BUY", price=c.close,
                    reason=f"Bollinger lower-band reversion (mean revert to {middle[i]:.2f})",
                    entry=c.close, stop_loss=stop, target=target,
                ))
                last_idx = i
            elif prev.close > upper[i - 1] and c.close < upper[i]:
                stop, target, _ = stop_target("SELL", c.close, atrs[i])
                out.append(Signal(
                    time=c.time, type="SELL", price=c.close,
                    reason=f"Bollinger upper-band reversion (mean revert to {middle[i]:.2f})",
                    entry=c.close, stop_loss=stop, target=target,
                ))
                last_idx = i
        return out
