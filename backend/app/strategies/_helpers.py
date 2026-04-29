"""Shared helpers for the new strategies.

All the indicator-driven strategies use the same risk-management template:
  - Stop is sized by 1.5 × ATR(14), clamped to [0.4%, 2.5%] of price
  - Target is 2× the stop distance (2R)
  - Cooldown bars between signals
"""
from __future__ import annotations

from ..indicators import atr
from ..schemas import Candle, Signal


STOP_ATR_MULT = 1.5
STOP_PCT_MIN = 0.004
STOP_PCT_MAX = 0.025
REWARD_R = 2.0
DEFAULT_COOLDOWN = 5


def stop_target(direction: str, price: float, atr_val: float) -> tuple[float, float, float]:
    """Returns (stop, target, stop_distance). direction: 'BUY' or 'SELL'."""
    dist = max(atr_val * STOP_ATR_MULT, price * STOP_PCT_MIN)
    dist = min(dist, price * STOP_PCT_MAX)
    if direction == "BUY":
        return price - dist, price + dist * REWARD_R, dist
    return price + dist, price - dist * REWARD_R, dist


def atr_array(candles: list[Candle], period: int = 14) -> list:
    return atr([c.high for c in candles], [c.low for c in candles], [c.close for c in candles], period)
