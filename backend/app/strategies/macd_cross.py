"""MACD crossover with EMA200 trend filter.

The textbook MACD signal — buy when MACD line crosses above its signal line —
fires far too often in chop. Adding the EMA200 trend filter (only longs in
uptrend, only shorts in downtrend) is the standard professional refinement.
"""
from ..indicators import ema, macd
from ..schemas import Candle, Signal
from .base import Strategy
from ._helpers import atr_array, stop_target, DEFAULT_COOLDOWN


class MACDCross(Strategy):
    id = "macd"
    name = "MACD Cross + EMA200 filter"
    description = "MACD(12,26,9) signal-line crossover, gated by price vs EMA200 trend."

    def evaluate(self, candles: list[Candle]) -> list[Signal]:
        if len(candles) < 250:
            return []
        closes = self.closes(candles)
        m_line, s_line, _ = macd(closes)
        e200 = ema(closes, 200)
        atrs = atr_array(candles)
        out: list[Signal] = []
        last_idx = -10**9
        for i in range(1, len(candles)):
            if i - last_idx < DEFAULT_COOLDOWN:
                continue
            m0, m1 = m_line[i - 1], m_line[i]
            s0, s1 = s_line[i - 1], s_line[i]
            if None in (m0, m1, s0, s1, e200[i], atrs[i]):
                continue
            c = candles[i]
            uptrend = c.close > e200[i]
            if uptrend and m0 <= s0 and m1 > s1:
                stop, target, _ = stop_target("BUY", c.close, atrs[i])
                out.append(Signal(
                    time=c.time, type="BUY", price=c.close,
                    reason=f"MACD bullish cross (above EMA200)",
                    entry=c.close, stop_loss=stop, target=target,
                ))
                last_idx = i
            elif (not uptrend) and m0 >= s0 and m1 < s1:
                stop, target, _ = stop_target("SELL", c.close, atrs[i])
                out.append(Signal(
                    time=c.time, type="SELL", price=c.close,
                    reason=f"MACD bearish cross (below EMA200)",
                    entry=c.close, stop_loss=stop, target=target,
                ))
                last_idx = i
        return out
