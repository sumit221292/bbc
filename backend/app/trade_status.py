"""Annotates signals with trade outcome by walking the candles forward.

For each signal that has entry/stop/target, we scan the bars *after* the signal
and decide whether the stop or target was hit first. If neither was hit by the
last loaded bar, the trade is OPEN and we report mark-to-market PnL.

A real trader would also want to handle slippage, fee, and intra-bar order; this
keeps it simple but honest — we use the bar's high/low to detect touches.
"""
from __future__ import annotations

from .schemas import Candle, Signal


def annotate(signals: list[Signal], candles: list[Candle]) -> list[Signal]:
    if not signals or not candles:
        return signals
    idx_by_time = {c.time: i for i, c in enumerate(candles)}
    last_close = candles[-1].close

    for s in signals:
        if s.entry is None or s.stop_loss is None or s.target is None:
            continue
        i = idx_by_time.get(s.time)
        if i is None:
            continue

        resolved = False
        for fc in candles[i + 1:]:
            if s.type == "BUY":
                hit_stop = fc.low <= s.stop_loss
                hit_target = fc.high >= s.target
                # If both happen in the same bar we conservatively assume stop first.
                if hit_stop:
                    s.status = "LOSS"
                    s.pnl_pct = (s.stop_loss - s.entry) / s.entry * 100.0
                    s.closed_at = fc.time
                    resolved = True
                    break
                if hit_target:
                    s.status = "WIN"
                    s.pnl_pct = (s.target - s.entry) / s.entry * 100.0
                    s.closed_at = fc.time
                    resolved = True
                    break
            else:  # SELL / short
                hit_stop = fc.high >= s.stop_loss
                hit_target = fc.low <= s.target
                if hit_stop:
                    s.status = "LOSS"
                    s.pnl_pct = (s.entry - s.stop_loss) / s.entry * 100.0
                    s.closed_at = fc.time
                    resolved = True
                    break
                if hit_target:
                    s.status = "WIN"
                    s.pnl_pct = (s.entry - s.target) / s.entry * 100.0
                    s.closed_at = fc.time
                    resolved = True
                    break

        if not resolved:
            s.status = "OPEN"
            if s.type == "BUY":
                s.pnl_pct = (last_close - s.entry) / s.entry * 100.0
            else:
                s.pnl_pct = (s.entry - last_close) / s.entry * 100.0

    return signals


def summarize(signals: list[Signal]) -> dict:
    """Quick win-rate / PnL summary used by the frontend status header."""
    closed = [s for s in signals if s.status in ("WIN", "LOSS")]
    wins = [s for s in closed if s.status == "WIN"]
    losses = [s for s in closed if s.status == "LOSS"]
    open_trades = [s for s in signals if s.status == "OPEN"]
    total_pnl = sum((s.pnl_pct or 0.0) for s in closed)
    return {
        "total": len(signals),
        "closed": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "open": len(open_trades),
        "win_rate": (len(wins) / len(closed) * 100.0) if closed else 0.0,
        "total_pnl_pct": total_pnl,
        "avg_pnl_pct": (total_pnl / len(closed)) if closed else 0.0,
    }
