from ..indicators import support_resistance
from ..schemas import Candle, Signal
from .base import Strategy


class SwingSRBounce(Strategy):
    id = "swing"
    name = "Swing Trading (S/R Bounce)"
    description = "Buy when price bounces off rolling support; sell when it rejects rolling resistance."

    LOOKBACK = 30
    TOLERANCE = 0.003  # within 0.3% of the level

    def evaluate(self, candles: list[Candle]) -> list[Signal]:
        if len(candles) < self.LOOKBACK + 2:
            return []
        out: list[Signal] = []
        for i in range(self.LOOKBACK, len(candles)):
            window = candles[i - self.LOOKBACK:i]
            sup, res = support_resistance(self.highs(window), self.lows(window), self.LOOKBACK)
            c = candles[i]
            prev = candles[i - 1]

            # Bounce off support: prior bar dipped near support, current bar closes higher.
            if prev.low <= sup * (1 + self.TOLERANCE) and c.close > prev.close and c.close > sup:
                out.append(Signal(
                    time=c.time, type="BUY", price=c.close,
                    reason=f"Bounced off support {sup:.2f}",
                    entry=c.close, stop_loss=sup * 0.995, target=res,
                ))
            # Rejection at resistance.
            elif prev.high >= res * (1 - self.TOLERANCE) and c.close < prev.close and c.close < res:
                out.append(Signal(
                    time=c.time, type="SELL", price=c.close,
                    reason=f"Rejected at resistance {res:.2f}",
                    entry=c.close, stop_loss=res * 1.005, target=sup,
                ))
        return out
