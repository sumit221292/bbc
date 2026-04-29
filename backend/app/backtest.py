"""Reusable trade simulator.

One open trade at a time, ATR-sized stops/targets come from the signal,
fixed % risk per trade with compounding, Binance spot fees per side.
"""
from __future__ import annotations

from .schemas import Candle, Signal


def simulate(
    candles: list[Candle],
    signals: list[Signal],
    start_idx: int = 0,
    capital: float = 1000.0,
    risk_pct: float = 0.02,
    fee_pct: float = 0.001,
) -> dict:
    sigs_by_time = {
        s.time: s for s in signals
        if s.entry is not None and s.stop_loss is not None and s.target is not None
    }
    cap = capital
    trades: list[dict] = []
    open_trade: dict | None = None

    for i in range(start_idx, len(candles)):
        c = candles[i]

        if open_trade is not None:
            exit_price = None
            outcome = None
            if open_trade["type"] == "BUY":
                if c.low <= open_trade["stop"]:
                    exit_price, outcome = open_trade["stop"], "LOSS"
                elif c.high >= open_trade["target"]:
                    exit_price, outcome = open_trade["target"], "WIN"
            else:
                if c.high >= open_trade["stop"]:
                    exit_price, outcome = open_trade["stop"], "LOSS"
                elif c.low <= open_trade["target"]:
                    exit_price, outcome = open_trade["target"], "WIN"

            if exit_price is not None:
                if open_trade["type"] == "BUY":
                    raw = (exit_price - open_trade["entry"]) * open_trade["size"]
                else:
                    raw = (open_trade["entry"] - exit_price) * open_trade["size"]
                fees = (open_trade["entry"] + exit_price) * open_trade["size"] * fee_pct
                pnl = raw - fees
                cap += pnl
                trades.append({"outcome": outcome, "pnl": pnl})
                open_trade = None

        sig = sigs_by_time.get(c.time)
        if sig is not None and open_trade is None:
            stop_dist = abs(sig.entry - sig.stop_loss)
            if stop_dist <= 0:
                continue
            size = (cap * risk_pct) / stop_dist
            open_trade = {
                "type": sig.type, "entry": sig.entry,
                "stop": sig.stop_loss, "target": sig.target,
                "size": size,
            }

    # Mark to market open trade at last close
    if open_trade is not None:
        last = candles[-1]
        if open_trade["type"] == "BUY":
            raw = (last.close - open_trade["entry"]) * open_trade["size"]
        else:
            raw = (open_trade["entry"] - last.close) * open_trade["size"]
        fees = (open_trade["entry"] + last.close) * open_trade["size"] * fee_pct
        pnl = raw - fees
        cap += pnl
        trades.append({"outcome": "OPEN", "pnl": pnl})

    wins = sum(1 for t in trades if t["outcome"] == "WIN")
    losses = sum(1 for t in trades if t["outcome"] == "LOSS")
    open_count = sum(1 for t in trades if t["outcome"] == "OPEN")
    closed = wins + losses
    return {
        "count": len(trades),
        "wins": wins,
        "losses": losses,
        "open": open_count,
        "win_rate": (wins / closed * 100.0) if closed else 0.0,
        "total_pnl_pct": (cap - capital) / capital * 100.0,
        "capital_end": cap,
    }
