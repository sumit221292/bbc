from ..indicators import ema
from ..schemas import Candle, Signal
from .base import Strategy


class TrendFollowing(Strategy):
    id = "trend_following"
    name = "Trend Following"
    description = "Buy when price climbs above both EMA50 and EMA200; sell when it loses both."

    MID = 50
    LONG = 200

    def evaluate(self, candles: list[Candle]) -> list[Signal]:
        if len(candles) < self.LONG + 2:
            return []
        closes = self.closes(candles)
        e50 = ema(closes, self.MID)
        e200 = ema(closes, self.LONG)
        out: list[Signal] = []
        # Track regime so we only emit on transitions.
        prev_state = 0  # -1 bear, 0 neutral, 1 bull
        for i in range(1, len(candles)):
            m, l = e50[i], e200[i]
            if m is None or l is None:
                continue
            c = candles[i]
            state = 1 if c.close > m and c.close > l else (-1 if c.close < m and c.close < l else 0)
            if state == 1 and prev_state != 1:
                out.append(Signal(
                    time=c.time, type="BUY", price=c.close,
                    reason="Price above EMA50 & EMA200 — bullish regime",
                    entry=c.close, stop_loss=l, target=c.close + (c.close - l),
                ))
            elif state == -1 and prev_state != -1:
                out.append(Signal(
                    time=c.time, type="SELL", price=c.close,
                    reason="Price below EMA50 & EMA200 — bearish regime",
                    entry=c.close, stop_loss=l, target=c.close - (l - c.close),
                ))
            prev_state = state
        return out
