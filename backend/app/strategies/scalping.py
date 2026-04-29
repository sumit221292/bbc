from ..indicators import rsi
from ..schemas import Candle, Signal
from .base import Strategy


class ScalpingRSI(Strategy):
    id = "scalping"
    name = "Scalping (RSI)"
    description = "Buy when RSI(14) crosses below 30, sell when it crosses above 70."

    OVERSOLD = 30.0
    OVERBOUGHT = 70.0
    PERIOD = 14

    def evaluate(self, candles: list[Candle]) -> list[Signal]:
        if len(candles) < self.PERIOD + 2:
            return []
        closes = self.closes(candles)
        r = rsi(closes, self.PERIOD)
        out: list[Signal] = []
        for i in range(1, len(candles)):
            prev, cur = r[i - 1], r[i]
            if prev is None or cur is None:
                continue
            c = candles[i]
            if prev >= self.OVERSOLD and cur < self.OVERSOLD:
                out.append(Signal(
                    time=c.time, type="BUY", price=c.close,
                    reason=f"RSI crossed below {self.OVERSOLD:.0f} ({cur:.1f})",
                    entry=c.close, stop_loss=c.low * 0.995, target=c.close * 1.01,
                ))
            elif prev <= self.OVERBOUGHT and cur > self.OVERBOUGHT:
                out.append(Signal(
                    time=c.time, type="SELL", price=c.close,
                    reason=f"RSI crossed above {self.OVERBOUGHT:.0f} ({cur:.1f})",
                    entry=c.close, stop_loss=c.high * 1.005, target=c.close * 0.99,
                ))
        return out
