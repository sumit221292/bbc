"""Smart Money Concepts (SMC) helpers — Order Block, Fair Value Gap (FVG),
Liquidity Sweep detection. Pure-Python, no external deps.

These are the building blocks ICT/SMC traders use to identify high-probability
zones. The functions are stateless — they look at a slice of candles around a
given index and return either None or a structured zone description.
"""
from __future__ import annotations

from .schemas import Candle


def detect_fvg(candles: list[Candle], i: int) -> dict | None:
    """3-candle Fair Value Gap (also called Imbalance) at bar i.

    Bullish FVG: candles[i-2].high < candles[i].low
        -> price gapped up; the unfilled zone is between those two prices.
        Price tends to retrace back into this gap to "fill" it.

    Bearish FVG: candles[i-2].low > candles[i].high
        -> mirror image, price gapped down.

    Returns {'type', 'top', 'bottom', 'idx'} or None.
    """
    if i < 2:
        return None
    a = candles[i - 2]
    c = candles[i]
    if a.high < c.low:
        return {"type": "bullish", "top": c.low, "bottom": a.high, "idx": i}
    if a.low > c.high:
        return {"type": "bearish", "top": a.low, "bottom": c.high, "idx": i}
    return None


def detect_recent_unfilled_fvg(candles: list[Candle], idx: int, direction: str,
                               lookback: int = 15) -> dict | None:
    """Find the most recent FVG of `direction` that is still UNFILLED
    by the candles between its formation and `idx`.

    Bullish FVG is "unfilled" if no later candle has dropped below its bottom.
    """
    for j in range(idx - 1, max(idx - lookback, 2) - 1, -1):
        fvg = detect_fvg(candles, j)
        if fvg is None or fvg["type"] != direction:
            continue
        between = candles[j + 1: idx + 1]
        if direction == "bullish":
            if all(k.low > fvg["bottom"] for k in between):
                return fvg
        else:
            if all(k.high < fvg["top"] for k in between):
                return fvg
    return None


def detect_order_block(candles: list[Candle], i: int,
                       lookahead: int = 5, min_move: float = 400.0,
                       max_idx: int | None = None) -> dict | None:
    """Order Block — the last opposite-direction candle before a strong impulse.

    Bullish OB: a bearish candle (close < open) followed by an up-move of
        at least `min_move` price points within the next `lookahead` bars.
        The OB zone is the bearish candle's body+wick range.

    Bearish OB: bullish candle followed by a strong down-move.

    `max_idx` caps the validation window so we don't look at candles beyond
    the current evaluation bar (avoids lookahead bias when called from a
    walk-forward strategy). Defaults to the end of the candle list.
    """
    if max_idx is None:
        max_idx = len(candles) - 1
    if i + lookahead > max_idx:
        return None
    c = candles[i]
    is_bearish_candle = c.close < c.open
    is_bullish_candle = c.close > c.open
    future = candles[i + 1: i + 1 + lookahead]
    if not future:
        return None
    high_after = max(k.high for k in future)
    low_after = min(k.low for k in future)

    if is_bearish_candle and (high_after - c.high) >= min_move:
        return {"type": "bullish", "top": c.high, "bottom": c.low, "idx": i}
    if is_bullish_candle and (c.low - low_after) >= min_move:
        return {"type": "bearish", "top": c.high, "bottom": c.low, "idx": i}
    return None


def find_recent_order_block(candles: list[Candle], idx: int, direction: str,
                            scan_back: int = 12, lookahead: int = 5,
                            min_move: float = 400.0) -> dict | None:
    """Search back up to `scan_back` bars for an order block matching direction
    that hasn't been violated yet (price hasn't fully crossed it back through)."""
    for back in range(1, scan_back + 1):
        j = idx - back
        if j < 2:
            break
        ob = detect_order_block(
            candles, j, lookahead=lookahead, min_move=min_move, max_idx=idx,
        )
        if ob is None or ob["type"] != direction:
            continue
        # Skip if the OB has already been "broken" (closed through it)
        between = candles[j + 1: idx]
        if direction == "bullish":
            # Bullish OB invalidated if any later candle closed below its bottom
            if any(k.close < ob["bottom"] for k in between):
                continue
        else:
            if any(k.close > ob["top"] for k in between):
                continue
        return ob
    return None


def detect_liquidity_sweep(candles: list[Candle], i: int,
                           lookback: int = 20) -> dict | None:
    """Did candle i sweep liquidity (stop-hunt)?

    Bullish sweep: low pierced the recent swing low but close came back above
        -> shorts got stopped out, smart-money likely accumulated longs.

    Bearish sweep: mirror.
    """
    if i < lookback:
        return None
    c = candles[i]
    window_highs = [k.high for k in candles[i - lookback: i]]
    window_lows = [k.low for k in candles[i - lookback: i]]
    swing_high = max(window_highs)
    swing_low = min(window_lows)
    if c.low < swing_low and c.close > swing_low:
        return {"type": "bullish_sweep", "level": swing_low}
    if c.high > swing_high and c.close < swing_high:
        return {"type": "bearish_sweep", "level": swing_high}
    return None
