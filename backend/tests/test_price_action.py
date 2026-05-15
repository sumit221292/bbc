"""Unit tests for the Price Action strategy.

Synthesises minimal candle sequences that should and should not fire the
pattern triggers, asserts the strategy responds correctly.

Run: python backend/tests/test_price_action.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from app.schemas import Candle
from app.strategies.price_action import PriceAction


def C(t, o, h, l, c, v=100.0):
    return Candle(time=t, open=o, high=h, low=l, close=c, volume=v)


def fail(msg):
    raise AssertionError(msg)


# ---------- Pattern detector unit tests ----------

def test_bullish_pin():
    print("[1] Bullish Pin Bar detection")
    pa = PriceAction()
    # Long lower wick, tiny upper wick, body in upper half — classic pin/hammer.
    pin = C(0, 100.0, 100.5, 95.0, 100.3)
    if not pa._is_bullish_pin(pin):
        fail("should detect bullish pin bar")
    # True doji: open == close, equal wicks on both sides -> not a pin.
    doji = C(0, 100.0, 102.5, 97.5, 100.0)
    if pa._is_bullish_pin(doji):
        fail("doji with equal wicks should not be a pin")
    # Equal wicks (not a pin)
    even = C(0, 100.0, 102.0, 98.0, 100.5)
    if pa._is_bullish_pin(even):
        fail("balanced candle should not be a pin")
    print("    OK")


def test_bearish_pin():
    print("[2] Bearish Pin Bar detection")
    pa = PriceAction()
    pin = C(0, 100.0, 105.0, 99.5, 99.7)
    if not pa._is_bearish_pin(pin):
        fail("should detect bearish pin")
    print("    OK")


def test_bullish_engulfing():
    print("[3] Bullish Engulfing detection")
    pa = PriceAction()
    prev = C(0, 100.0, 100.5, 98.0, 98.5)   # red
    curr = C(1, 98.4, 101.0, 98.0, 100.8)   # green that engulfs prev body
    if not pa._is_bullish_engulfing(prev, curr):
        fail("should detect bullish engulfing")
    # Negative: prev green
    prev_g = C(0, 98.0, 100.5, 98.0, 100.0)
    curr_g = C(1, 99.8, 101.0, 99.0, 100.8)
    if pa._is_bullish_engulfing(prev_g, curr_g):
        fail("prev green disqualifies bullish engulfing")
    print("    OK")


def test_bearish_engulfing():
    print("[4] Bearish Engulfing detection")
    pa = PriceAction()
    prev = C(0, 98.0, 100.5, 98.0, 100.0)   # green
    curr = C(1, 100.1, 100.5, 97.0, 97.5)   # red that engulfs prev body
    if not pa._is_bearish_engulfing(prev, curr):
        fail("should detect bearish engulfing")
    print("    OK")


# ---------- Full strategy flow test ----------

# 60-bar chop pattern establishes 95 as support, ~104 as resistance.
_CHOP_60 = [95, 96, 100, 98, 102, 95, 97, 103, 99, 95,
            97, 101, 96, 99, 104, 98, 96, 102, 95, 100,
            97, 99, 96, 103, 101, 95, 98, 100, 96, 102,
            97, 95, 99, 101, 96, 98, 95, 100, 97, 99,
            96, 102, 98, 95, 100, 96, 99, 101, 97, 95,
            98, 103, 96, 100, 95, 102, 97, 99, 96, 100]


def _build_chop():
    candles = []
    t = 0
    for px in _CHOP_60:
        candles.append(C(t, px, px + 0.5, px - 0.5, px))
        t += 60
    return candles, t


def make_chop_then_bounce():
    """Chop range builds 95 as support, final bar is a bullish pin at 95."""
    candles, t = _build_chop()
    candles.append(C(t, 96.0, 96.3, 94.6, 96.2))
    return candles


def make_chop_then_rejection():
    """Chop range builds ~104 as resistance, final bar is a bearish pin there."""
    candles, t = _build_chop()
    candles.append(C(t, 103.0, 104.4, 102.7, 102.8))
    return candles


def test_buy_signal_at_support():
    print("[5] BUY signal fires at support pin bar")
    sigs = PriceAction().evaluate(make_chop_then_bounce())
    last = sigs[-1] if sigs else None
    if last is None or last.type != "BUY":
        fail(f"expected BUY, got {last}")
    if last.stop_loss is None or last.stop_loss >= last.entry:
        fail(f"stop should be below entry, got {last.stop_loss} >= {last.entry}")
    if last.target is None or last.target <= last.entry:
        fail(f"target should be above entry, got {last.target} <= {last.entry}")
    rr = (last.target - last.entry) / (last.entry - last.stop_loss)
    if rr < 1.99:
        fail(f"RR should be >= 2.0 (router floor); got {rr:.3f}")
    print(f"    OK -- BUY entry={last.entry:.2f} stop={last.stop_loss:.2f} target={last.target:.2f} RR=1:{rr:.2f}")
    print(f"           reason: {last.reason}")


def test_sell_signal_at_resistance():
    print("[6] SELL signal fires at resistance pin bar")
    sigs = PriceAction().evaluate(make_chop_then_rejection())
    last = sigs[-1] if sigs else None
    if last is None or last.type != "SELL":
        fail(f"expected SELL, got {last}")
    if last.stop_loss is None or last.stop_loss <= last.entry:
        fail(f"stop should be above entry, got {last.stop_loss} <= {last.entry}")
    if last.target is None or last.target >= last.entry:
        fail(f"target should be below entry, got {last.target} >= {last.entry}")
    rr = (last.entry - last.target) / (last.stop_loss - last.entry)
    if rr < 1.99:
        fail(f"RR should be >= 2.0; got {rr:.3f}")
    print(f"    OK -- SELL entry={last.entry:.2f} stop={last.stop_loss:.2f} target={last.target:.2f} RR=1:{rr:.2f}")
    print(f"           reason: {last.reason}")


def test_no_signal_in_chop_without_pattern():
    print("[7] No signal in pure chop without a pattern at S/R")
    # Same chop history but final bar is a small neutral candle far from S/R.
    candles = make_chop_then_bounce()[:-1]
    candles.append(C(candles[-1].time + 60, 99.0, 99.4, 98.6, 99.2))
    sigs = PriceAction().evaluate(candles)
    # Either no signals at all, or last signal is not on the final bar.
    if sigs and sigs[-1].time == candles[-1].time:
        fail(f"should not fire on neutral mid-range bar; got {sigs[-1]}")
    print("    OK -- no spurious signal")


# ---------- Runner ----------

def main():
    try:
        test_bullish_pin()
        test_bearish_pin()
        test_bullish_engulfing()
        test_bearish_engulfing()
        test_buy_signal_at_support()
        test_sell_signal_at_resistance()
        test_no_signal_in_chop_without_pattern()
        print("\nALL 7 SCENARIOS PASSED")
        return 0
    except AssertionError as e:
        print(f"\nFAIL: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
