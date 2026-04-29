"""Vectorised indicator helpers — used by strategies.

Inputs/outputs are plain lists of floats so they're trivially JSON-serialisable.
NaNs (warm-up periods) are returned as None for clean frontend handling.
"""
from __future__ import annotations

from typing import Optional
import numpy as np


def _to_optional(arr: np.ndarray) -> list[Optional[float]]:
    return [None if np.isnan(x) else float(x) for x in arr]


def ema(values: list[float], period: int) -> list[Optional[float]]:
    """Standard exponential moving average. Seeds from the first SMA window."""
    if not values or period <= 0:
        return [None] * len(values)
    arr = np.asarray(values, dtype=float)
    out = np.full_like(arr, np.nan)
    if len(arr) < period:
        return _to_optional(out)
    k = 2.0 / (period + 1.0)
    seed = arr[:period].mean()
    out[period - 1] = seed
    prev = seed
    for i in range(period, len(arr)):
        prev = arr[i] * k + prev * (1.0 - k)
        out[i] = prev
    return _to_optional(out)


def rsi(values: list[float], period: int = 14) -> list[Optional[float]]:
    """Wilder's RSI."""
    if not values:
        return []
    arr = np.asarray(values, dtype=float)
    out = np.full_like(arr, np.nan)
    if len(arr) <= period:
        return _to_optional(out)

    deltas = np.diff(arr)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = gains[:period].mean()
    avg_loss = losses[:period].mean()
    out[period] = 100.0 if avg_loss == 0 else 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))

    for i in range(period + 1, len(arr)):
        g = gains[i - 1]
        l = losses[i - 1]
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period
        out[i] = 100.0 if avg_loss == 0 else 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))

    return _to_optional(out)


def support_resistance(highs: list[float], lows: list[float], lookback: int = 20) -> tuple[float, float]:
    """Naive S/R: rolling high/low over the lookback window."""
    if not highs or not lows:
        return 0.0, 0.0
    h = np.asarray(highs[-lookback:], dtype=float)
    l = np.asarray(lows[-lookback:], dtype=float)
    return float(l.min()), float(h.max())


def _ema_np(arr: np.ndarray, period: int) -> np.ndarray:
    """Internal numpy EMA — used by composite indicators (MACD etc.)."""
    out = np.full_like(arr, np.nan)
    if len(arr) < period or period <= 0:
        return out
    k = 2.0 / (period + 1.0)
    seed = arr[:period].mean()
    out[period - 1] = seed
    prev = seed
    for i in range(period, len(arr)):
        prev = arr[i] * k + prev * (1.0 - k)
        out[i] = prev
    return out


def macd(closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9):
    """Returns (macd_line, signal_line, histogram) — three lists with None warmup."""
    arr = np.asarray(closes, dtype=float)
    n = len(arr)
    fast_e = _ema_np(arr, fast)
    slow_e = _ema_np(arr, slow)
    macd_line = fast_e - slow_e  # NaN propagates from either side

    sig = np.full(n, np.nan)
    valid_start = slow - 1
    if n > valid_start + signal:
        sig_valid = _ema_np(macd_line[valid_start:], signal)
        sig[valid_start:] = sig_valid
    hist = macd_line - sig
    return _to_optional(macd_line), _to_optional(sig), _to_optional(hist)


def bollinger(closes: list[float], period: int = 20, k: float = 2.0):
    """Returns (upper, middle, lower) Bollinger Bands."""
    arr = np.asarray(closes, dtype=float)
    n = len(arr)
    upper = np.full(n, np.nan)
    middle = np.full(n, np.nan)
    lower = np.full(n, np.nan)
    if n < period:
        return _to_optional(upper), _to_optional(middle), _to_optional(lower)
    for i in range(period - 1, n):
        window = arr[i - period + 1:i + 1]
        m = window.mean()
        s = window.std(ddof=0)
        middle[i] = m
        upper[i] = m + k * s
        lower[i] = m - k * s
    return _to_optional(upper), _to_optional(middle), _to_optional(lower)


def stochastic(highs: list[float], lows: list[float], closes: list[float],
               k_period: int = 14, d_period: int = 3):
    """Returns (%K, %D) — slow stochastic with simple smoothing."""
    h = np.asarray(highs, dtype=float)
    l = np.asarray(lows, dtype=float)
    c = np.asarray(closes, dtype=float)
    n = len(c)
    k = np.full(n, np.nan)
    if n < k_period:
        return _to_optional(k), _to_optional(k)
    for i in range(k_period - 1, n):
        hh = h[i - k_period + 1:i + 1].max()
        ll = l[i - k_period + 1:i + 1].min()
        rng = hh - ll
        k[i] = 100.0 * (c[i] - ll) / rng if rng > 0 else 50.0
    # %D = SMA of %K
    d = np.full(n, np.nan)
    for i in range(k_period - 1 + d_period - 1, n):
        d[i] = np.nanmean(k[i - d_period + 1:i + 1])
    return _to_optional(k), _to_optional(d)


def donchian(highs: list[float], lows: list[float], period: int = 20):
    """Returns (upper, lower) Donchian channels (rolling highest/lowest excluding current bar)."""
    h = np.asarray(highs, dtype=float)
    l = np.asarray(lows, dtype=float)
    n = len(h)
    up = np.full(n, np.nan)
    lo = np.full(n, np.nan)
    for i in range(period, n):
        up[i] = h[i - period:i].max()
        lo[i] = l[i - period:i].min()
    return _to_optional(up), _to_optional(lo)


def supertrend(highs: list[float], lows: list[float], closes: list[float],
               period: int = 10, mult: float = 3.0):
    """Returns (supertrend_line, direction) where direction is +1 (uptrend) / -1 (downtrend)."""
    h = np.asarray(highs, dtype=float)
    l = np.asarray(lows, dtype=float)
    c = np.asarray(closes, dtype=float)
    n = len(c)
    a = atr(highs, lows, closes, period)
    a_arr = np.array([np.nan if x is None else x for x in a])

    hl2 = (h + l) / 2.0
    upper = hl2 + mult * a_arr
    lower = hl2 - mult * a_arr

    st = np.full(n, np.nan)
    direction = np.full(n, np.nan)

    # Find first valid bar (where ATR exists)
    first = period
    if first >= n:
        return _to_optional(st), _to_optional(direction)

    # Initialise — assume downtrend if close < lower band; else uptrend
    direction[first] = 1.0 if c[first] > lower[first] else -1.0
    st[first] = lower[first] if direction[first] == 1.0 else upper[first]

    for i in range(first + 1, n):
        prev_st = st[i - 1]
        prev_dir = direction[i - 1]

        # "Final" bands: ratchet only one way
        if prev_dir == 1.0:
            cur_lower = max(lower[i], prev_st)
            if c[i] < cur_lower:
                direction[i] = -1.0
                st[i] = upper[i]
            else:
                direction[i] = 1.0
                st[i] = cur_lower
        else:
            cur_upper = min(upper[i], prev_st)
            if c[i] > cur_upper:
                direction[i] = 1.0
                st[i] = lower[i]
            else:
                direction[i] = -1.0
                st[i] = cur_upper
    return _to_optional(st), _to_optional(direction)


def adx(highs: list[float], lows: list[float], closes: list[float], period: int = 14):
    """Returns (adx, +DI, -DI) using Wilder smoothing."""
    h = np.asarray(highs, dtype=float)
    l = np.asarray(lows, dtype=float)
    c = np.asarray(closes, dtype=float)
    n = len(c)
    out_adx = np.full(n, np.nan)
    out_pdi = np.full(n, np.nan)
    out_mdi = np.full(n, np.nan)
    if n < period * 2:
        return _to_optional(out_adx), _to_optional(out_pdi), _to_optional(out_mdi)

    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    tr = np.zeros(n)
    for i in range(1, n):
        up_move = h[i] - h[i - 1]
        down_move = l[i - 1] - l[i]
        plus_dm[i] = up_move if (up_move > down_move and up_move > 0) else 0.0
        minus_dm[i] = down_move if (down_move > up_move and down_move > 0) else 0.0
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))

    # Wilder smoothing
    atr_w = np.zeros(n)
    pdm_w = np.zeros(n)
    mdm_w = np.zeros(n)
    atr_w[period] = tr[1:period + 1].sum()
    pdm_w[period] = plus_dm[1:period + 1].sum()
    mdm_w[period] = minus_dm[1:period + 1].sum()
    for i in range(period + 1, n):
        atr_w[i] = atr_w[i - 1] - atr_w[i - 1] / period + tr[i]
        pdm_w[i] = pdm_w[i - 1] - pdm_w[i - 1] / period + plus_dm[i]
        mdm_w[i] = mdm_w[i - 1] - mdm_w[i - 1] / period + minus_dm[i]

    pdi = np.full(n, np.nan)
    mdi = np.full(n, np.nan)
    dx = np.full(n, np.nan)
    for i in range(period, n):
        if atr_w[i] > 0:
            pdi[i] = 100.0 * pdm_w[i] / atr_w[i]
            mdi[i] = 100.0 * mdm_w[i] / atr_w[i]
            denom = pdi[i] + mdi[i]
            dx[i] = 100.0 * abs(pdi[i] - mdi[i]) / denom if denom > 0 else 0.0

    # ADX = Wilder smoothing of DX
    out_adx = np.full(n, np.nan)
    if n > 2 * period:
        out_adx[2 * period - 1] = np.nanmean(dx[period:2 * period])
        for i in range(2 * period, n):
            out_adx[i] = (out_adx[i - 1] * (period - 1) + dx[i]) / period
    return _to_optional(out_adx), _to_optional(pdi), _to_optional(mdi)


def ichimoku(highs: list[float], lows: list[float], closes: list[float],
             tenkan_p: int = 9, kijun_p: int = 26, senkou_p: int = 52):
    """Returns (tenkan, kijun, senkou_a, senkou_b) — cloud is between span A and B.
    Note: senkou spans are NOT shifted forward here (we work bar-aligned for backtesting)."""
    h = np.asarray(highs, dtype=float)
    l = np.asarray(lows, dtype=float)
    n = len(h)
    tenkan = np.full(n, np.nan)
    kijun = np.full(n, np.nan)
    span_a = np.full(n, np.nan)
    span_b = np.full(n, np.nan)
    for i in range(senkou_p - 1, n):
        if i >= tenkan_p - 1:
            tenkan[i] = (h[i - tenkan_p + 1:i + 1].max() + l[i - tenkan_p + 1:i + 1].min()) / 2.0
        if i >= kijun_p - 1:
            kijun[i] = (h[i - kijun_p + 1:i + 1].max() + l[i - kijun_p + 1:i + 1].min()) / 2.0
        if not (np.isnan(tenkan[i]) or np.isnan(kijun[i])):
            span_a[i] = (tenkan[i] + kijun[i]) / 2.0
        span_b[i] = (h[i - senkou_p + 1:i + 1].max() + l[i - senkou_p + 1:i + 1].min()) / 2.0
    return _to_optional(tenkan), _to_optional(kijun), _to_optional(span_a), _to_optional(span_b)


def atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[Optional[float]]:
    """Average True Range (Wilder smoothing).

    ATR is the natural way to size stops because it adapts to current volatility:
    a $1000 stop is huge when BTC is moving $200/day and tiny when it's moving $5000/day.
    """
    n = len(closes)
    if n == 0:
        return []
    out = np.full(n, np.nan)
    if n <= period:
        return _to_optional(out)
    h = np.asarray(highs, dtype=float)
    l = np.asarray(lows, dtype=float)
    c = np.asarray(closes, dtype=float)
    # True range for bar i needs c[i-1], so trs[0] is undefined; we align indices to bar i.
    trs = np.zeros(n)
    trs[0] = h[0] - l[0]
    for i in range(1, n):
        trs[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    # Wilder smoothing
    seed = trs[1:period + 1].mean()
    out[period] = seed
    prev = seed
    for i in range(period + 1, n):
        prev = (prev * (period - 1) + trs[i]) / period
        out[i] = prev
    return _to_optional(out)
