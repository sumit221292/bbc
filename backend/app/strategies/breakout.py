import numpy as np

from ..indicators import support_resistance
from ..schemas import Candle, Signal
from .base import Strategy


class Breakout(Strategy):
    id = "breakout"
    name = "Breakout Trading"
    description = "Buy when price breaks rolling resistance on above-average volume; sell on support break with volume."

    LOOKBACK = 20
    VOL_MULT = 1.5  # current volume must be >= mean * VOL_MULT

    def evaluate(self, candles: list[Candle]) -> list[Signal]:
        if len(candles) < self.LOOKBACK + 2:
            return []
        out: list[Signal] = []
        for i in range(self.LOOKBACK, len(candles)):
            window = candles[i - self.LOOKBACK:i]
            sup, res = support_resistance(self.highs(window), self.lows(window), self.LOOKBACK)
            avg_vol = float(np.mean(self.volumes(window)))
            c = candles[i]
            if avg_vol == 0:
                continue
            if c.close > res and c.volume >= avg_vol * self.VOL_MULT:
                out.append(Signal(
                    time=c.time, type="BUY", price=c.close,
                    reason=f"Broke resistance {res:.2f} on {c.volume / avg_vol:.1f}× avg volume",
                    entry=c.close, stop_loss=res * 0.995, target=c.close + (c.close - sup) * 0.5,
                ))
            elif c.close < sup and c.volume >= avg_vol * self.VOL_MULT:
                out.append(Signal(
                    time=c.time, type="SELL", price=c.close,
                    reason=f"Broke support {sup:.2f} on {c.volume / avg_vol:.1f}× avg volume",
                    entry=c.close, stop_loss=sup * 1.005, target=c.close - (res - c.close) * 0.5,
                ))
        return out
