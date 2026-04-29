"""Donchian Channel breakout — the classic Turtle Trader system.

Buy when price closes above the prior 20-bar high; sell when it closes below
the prior 20-bar low. The original Turtles traded this without targets, exiting
on a 10-bar opposite breakout. We use a fixed 2R target for consistency with
the rest of the suite.
"""
from ..indicators import donchian
from ..schemas import Candle, Signal
from .base import Strategy
from ._helpers import atr_array, stop_target, DEFAULT_COOLDOWN


class DonchianTurtle(Strategy):
    id = "donchian"
    name = "Donchian Breakout (Turtle)"
    description = "Buy on close above 20-bar high; sell on close below 20-bar low."

    def evaluate(self, candles: list[Candle]) -> list[Signal]:
        if len(candles) < 30:
            return []
        upper, lower = donchian(self.highs(candles), self.lows(candles), 20)
        atrs = atr_array(candles)
        out: list[Signal] = []
        last_idx = -10**9
        for i in range(20, len(candles)):
            if i - last_idx < DEFAULT_COOLDOWN:
                continue
            if upper[i] is None or lower[i] is None or atrs[i] is None:
                continue
            c = candles[i]
            if c.close > upper[i]:
                stop, target, _ = stop_target("BUY", c.close, atrs[i])
                out.append(Signal(
                    time=c.time, type="BUY", price=c.close,
                    reason=f"Close broke above 20-bar high {upper[i]:.2f}",
                    entry=c.close, stop_loss=stop, target=target,
                ))
                last_idx = i
            elif c.close < lower[i]:
                stop, target, _ = stop_target("SELL", c.close, atrs[i])
                out.append(Signal(
                    time=c.time, type="SELL", price=c.close,
                    reason=f"Close broke below 20-bar low {lower[i]:.2f}",
                    entry=c.close, stop_loss=stop, target=target,
                ))
                last_idx = i
        return out
