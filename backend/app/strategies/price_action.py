"""Price Action — pure candle structure at support/resistance.

Two classical PA triggers, no indicators on the chart:
  1. Pin Bar (rejection wick) at a fresh S/R level
  2. Engulfing candle at a fresh S/R level

Trade direction is dictated by which level was tested:
  - Pin/engulf near rolling support  -> BUY (bounce play)
  - Pin/engulf near rolling resistance -> SELL (rejection play)

Stop is placed beyond the pattern's extreme wick (with a small buffer) so a
single failed retest invalidates the setup. Target prefers the opposite
S/R level but always honours the 1:2 RR floor enforced by the router.
"""
from __future__ import annotations

from ..indicators import atr, support_resistance
from ..schemas import Candle, Signal
from .base import Strategy
from ._helpers import REWARD_R


class PriceAction(Strategy):
    id = "price_action"
    name = "📊 Price Action (Pin Bar + Engulfing at S/R)"
    description = (
        "No indicators — pure candle structure. Fires when a pin bar or "
        "engulfing candle prints within tolerance of rolling support or "
        "resistance. Cleanest discretionary-style setups."
    )

    LOOKBACK = 30           # bars used to compute the rolling S/R level
    TOLERANCE = 0.004       # 0.4% — how close to the level the pattern must be
    COOLDOWN = 5            # bars between signals to avoid clustering
    # Pin bar uses range-based detection: the rejection wick must be a
    # dominant share of the total candle range. More robust than wick/body
    # ratios when the body is tiny.
    PIN_WICK_OF_RANGE = 0.60   # rejecting wick must be >= 60% of range
    PIN_BODY_OF_RANGE = 0.40   # body must be <= 40% of range
    PIN_OPP_OF_RANGE  = 0.20   # opposite wick must be <= 20% of range
    MIN_RANGE_PCT     = 0.001  # candle range >= 0.1% of price (skip dojis)
    STOP_BUFFER       = 0.001  # 0.1% buffer past the pattern wick

    # --- candle math helpers ---
    @staticmethod
    def _body(c: Candle) -> float:
        return abs(c.close - c.open)

    @staticmethod
    def _upper_wick(c: Candle) -> float:
        return c.high - max(c.open, c.close)

    @staticmethod
    def _lower_wick(c: Candle) -> float:
        return min(c.open, c.close) - c.low

    def _is_bullish_pin(self, c: Candle) -> bool:
        rng = c.high - c.low
        if rng <= 0 or rng < c.close * self.MIN_RANGE_PCT:
            return False
        lower = self._lower_wick(c)
        upper = self._upper_wick(c)
        body  = self._body(c)
        return (lower / rng >= self.PIN_WICK_OF_RANGE
                and body  / rng <= self.PIN_BODY_OF_RANGE
                and upper / rng <= self.PIN_OPP_OF_RANGE)

    def _is_bearish_pin(self, c: Candle) -> bool:
        rng = c.high - c.low
        if rng <= 0 or rng < c.close * self.MIN_RANGE_PCT:
            return False
        upper = self._upper_wick(c)
        lower = self._lower_wick(c)
        body  = self._body(c)
        return (upper / rng >= self.PIN_WICK_OF_RANGE
                and body  / rng <= self.PIN_BODY_OF_RANGE
                and lower / rng <= self.PIN_OPP_OF_RANGE)

    @staticmethod
    def _is_bullish_engulfing(prev: Candle, c: Candle) -> bool:
        prev_red = prev.close < prev.open
        curr_green = c.close > c.open
        engulfs = c.open <= prev.close and c.close >= prev.open
        return prev_red and curr_green and engulfs

    @staticmethod
    def _is_bearish_engulfing(prev: Candle, c: Candle) -> bool:
        prev_green = prev.close > prev.open
        curr_red = c.close < c.open
        engulfs = c.open >= prev.close and c.close <= prev.open
        return prev_green and curr_red and engulfs

    def evaluate(self, candles: list[Candle]) -> list[Signal]:
        n = len(candles)
        if n < self.LOOKBACK + 20:
            return []

        atr_vals = atr(self.highs(candles), self.lows(candles), self.closes(candles), 14)

        out: list[Signal] = []
        last_sig_idx = -10**9

        for i in range(self.LOOKBACK, n):
            if i - last_sig_idx < self.COOLDOWN:
                continue

            c = candles[i]
            prev = candles[i - 1]
            window = candles[i - self.LOOKBACK:i]
            sup, res = support_resistance(self.highs(window), self.lows(window), self.LOOKBACK)
            a = atr_vals[i] if atr_vals[i] is not None else c.close * 0.005

            # Position relative to S/R. Tolerance is symmetric so a wick that
            # pokes through still qualifies as "at" the level.
            near_support    = c.low  <= sup * (1 + self.TOLERANCE) and c.close > sup
            near_resistance = c.high >= res * (1 - self.TOLERANCE) and c.close < res

            # --- BUY: bullish pattern at support ---
            if near_support:
                pattern = (
                    "Bull Pin Bar" if self._is_bullish_pin(c) else
                    "Bull Engulfing" if self._is_bullish_engulfing(prev, c) else
                    None
                )
                if pattern is not None:
                    stop = c.low * (1 - self.STOP_BUFFER)
                    # Use the opposite level as the natural target; fall back
                    # to a 2R distance if R is too close to honour the RR floor.
                    risk = c.close - stop
                    target_via_r = c.close + risk * REWARD_R
                    target = max(res, target_via_r) if res > c.close else target_via_r
                    out.append(Signal(
                        time=c.time, type="BUY", price=c.close,
                        reason=f"{pattern} at support {sup:.2f}",
                        entry=c.close, stop_loss=stop, target=target,
                    ))
                    last_sig_idx = i
                    continue

            # --- SELL: bearish pattern at resistance ---
            if near_resistance:
                pattern = (
                    "Bear Pin Bar" if self._is_bearish_pin(c) else
                    "Bear Engulfing" if self._is_bearish_engulfing(prev, c) else
                    None
                )
                if pattern is not None:
                    stop = c.high * (1 + self.STOP_BUFFER)
                    risk = stop - c.close
                    target_via_r = c.close - risk * REWARD_R
                    target = min(sup, target_via_r) if sup < c.close else target_via_r
                    out.append(Signal(
                        time=c.time, type="SELL", price=c.close,
                        reason=f"{pattern} at resistance {res:.2f}",
                        entry=c.close, stop_loss=stop, target=target,
                    ))
                    last_sig_idx = i

        return out
