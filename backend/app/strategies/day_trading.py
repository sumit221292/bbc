from ..indicators import ema
from ..schemas import Candle, Signal
from .base import Strategy


class DayTradingEMACross(Strategy):
    id = "day_trading"
    name = "Day Trading (EMA Crossover)"
    description = "Buy on EMA(20) crossing above EMA(50); sell on the inverse cross."

    FAST = 20
    SLOW = 50

    def evaluate(self, candles: list[Candle]) -> list[Signal]:
        if len(candles) < self.SLOW + 2:
            return []
        closes = self.closes(candles)
        fast = ema(closes, self.FAST)
        slow = ema(closes, self.SLOW)
        out: list[Signal] = []
        for i in range(1, len(candles)):
            f0, f1 = fast[i - 1], fast[i]
            s0, s1 = slow[i - 1], slow[i]
            if None in (f0, f1, s0, s1):
                continue
            c = candles[i]
            if f0 <= s0 and f1 > s1:
                out.append(Signal(
                    time=c.time, type="BUY", price=c.close,
                    reason=f"EMA{self.FAST} crossed above EMA{self.SLOW}",
                    entry=c.close, stop_loss=s1, target=c.close + (c.close - s1) * 2,
                ))
            elif f0 >= s0 and f1 < s1:
                out.append(Signal(
                    time=c.time, type="SELL", price=c.close,
                    reason=f"EMA{self.FAST} crossed below EMA{self.SLOW}",
                    entry=c.close, stop_loss=s1, target=c.close - (s1 - c.close) * 2,
                ))
        return out
