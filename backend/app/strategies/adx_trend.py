"""ADX trend-strength filter on a directional cross.

Only trades when the trend is strong (ADX > 25):
  BUY  when +DI crosses above -DI and ADX > 25
  SELL when -DI crosses above +DI and ADX > 25
ADX measures how *much* trend exists, not direction. Combining it with the DI
cross gives a high-probability trend-entry signal.
"""
from ..indicators import adx
from ..schemas import Candle, Signal
from .base import Strategy
from ._helpers import atr_array, stop_target, DEFAULT_COOLDOWN


class ADXTrend(Strategy):
    id = "adx_trend"
    name = "ADX + DI Trend Entry"
    description = "Directional Indicator cross when ADX > 25 (strong trend)."

    ADX_MIN = 25.0

    def evaluate(self, candles: list[Candle]) -> list[Signal]:
        if len(candles) < 60:
            return []
        a, pdi, mdi = adx(self.highs(candles), self.lows(candles), self.closes(candles), 14)
        atrs = atr_array(candles)
        out: list[Signal] = []
        last_idx = -10**9
        for i in range(1, len(candles)):
            if i - last_idx < DEFAULT_COOLDOWN:
                continue
            if None in (a[i], pdi[i], mdi[i], pdi[i - 1], mdi[i - 1], atrs[i]):
                continue
            if a[i] < self.ADX_MIN:
                continue
            c = candles[i]
            if pdi[i - 1] <= mdi[i - 1] and pdi[i] > mdi[i]:
                stop, target, _ = stop_target("BUY", c.close, atrs[i])
                out.append(Signal(
                    time=c.time, type="BUY", price=c.close,
                    reason=f"+DI crossed -DI, ADX={a[i]:.1f}",
                    entry=c.close, stop_loss=stop, target=target,
                ))
                last_idx = i
            elif mdi[i - 1] <= pdi[i - 1] and mdi[i] > pdi[i]:
                stop, target, _ = stop_target("SELL", c.close, atrs[i])
                out.append(Signal(
                    time=c.time, type="SELL", price=c.close,
                    reason=f"-DI crossed +DI, ADX={a[i]:.1f}",
                    entry=c.close, stop_loss=stop, target=target,
                ))
                last_idx = i
        return out
