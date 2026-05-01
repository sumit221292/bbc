"""Reusable trade simulator.

One open trade at a time, ATR-sized stops/targets come from the signal,
fixed % risk per trade with compounding, Binance spot fees per side.

Optional partial-target / breakeven-stop mode:
  - Pass `partial_at_r=1.0` to scale out 50% of the position when price
    reaches 1R, then move the stop to entry (breakeven) for the remaining
    50%, which then targets the original 2R target. This caps the
    downside and converts breakeven exits into "free trades" -- raises
    expectancy even with the same win rate.
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
    partial_at_r: float | None = None,
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
            t = open_trade
            stop_dist = abs(t["initial_entry"] - t["initial_stop"])
            partial_target = (
                t["initial_entry"] + stop_dist * partial_at_r
                if partial_at_r and t["type"] == "BUY"
                else t["initial_entry"] - stop_dist * partial_at_r
                if partial_at_r and t["type"] == "SELL"
                else None
            )

            # Detect partial-target hit (only once per trade)
            if (partial_target is not None and not t["partial_done"]
                    and ((t["type"] == "BUY" and c.high >= partial_target)
                         or (t["type"] == "SELL" and c.low <= partial_target))):
                # Close 50% at partial target
                half = t["size"] * 0.5
                if t["type"] == "BUY":
                    raw = (partial_target - t["initial_entry"]) * half
                else:
                    raw = (t["initial_entry"] - partial_target) * half
                fees = (t["initial_entry"] + partial_target) * half * fee_pct
                pnl_partial = raw - fees
                cap += pnl_partial
                t["partial_pnl"] = pnl_partial
                t["remaining_size"] = t["size"] - half
                t["partial_done"] = True
                t["stop"] = t["initial_entry"]  # move to breakeven

            # Now check stop / final target on the current bar
            exit_price = None
            outcome = None
            if t["type"] == "BUY":
                if c.low <= t["stop"]:
                    exit_price = t["stop"]
                    # If stop is at BE (i.e., partial already taken), call this WIN
                    outcome = "WIN" if t["partial_done"] else "LOSS"
                elif c.high >= t["target"]:
                    exit_price = t["target"]
                    outcome = "WIN"
            else:
                if c.high >= t["stop"]:
                    exit_price = t["stop"]
                    outcome = "WIN" if t["partial_done"] else "LOSS"
                elif c.low <= t["target"]:
                    exit_price = t["target"]
                    outcome = "WIN"

            if exit_price is not None:
                if t["type"] == "BUY":
                    raw = (exit_price - t["initial_entry"]) * t["remaining_size"]
                else:
                    raw = (t["initial_entry"] - exit_price) * t["remaining_size"]
                fees = (t["initial_entry"] + exit_price) * t["remaining_size"] * fee_pct
                pnl_final = raw - fees
                cap += pnl_final
                trades.append({
                    "outcome": outcome,
                    "pnl": pnl_final + t.get("partial_pnl", 0.0),
                })
                open_trade = None

        # New entry?
        sig = sigs_by_time.get(c.time)
        if sig is not None and open_trade is None:
            stop_dist = abs(sig.entry - sig.stop_loss)
            if stop_dist <= 0:
                continue
            size = (cap * risk_pct) / stop_dist
            open_trade = {
                "type": sig.type,
                "initial_entry": sig.entry,
                "initial_stop": sig.stop_loss,
                "stop": sig.stop_loss,
                "target": sig.target,
                "size": size,
                "remaining_size": size,
                "partial_done": False,
                "partial_pnl": 0.0,
            }

    # Mark to market open trade at last close
    if open_trade is not None:
        t = open_trade
        last = candles[-1]
        if t["type"] == "BUY":
            raw = (last.close - t["initial_entry"]) * t["remaining_size"]
        else:
            raw = (t["initial_entry"] - last.close) * t["remaining_size"]
        fees = (t["initial_entry"] + last.close) * t["remaining_size"] * fee_pct
        pnl_final = raw - fees
        cap += pnl_final
        trades.append({
            "outcome": "OPEN",
            "pnl": pnl_final + t.get("partial_pnl", 0.0),
        })

    wins = sum(1 for tr in trades if tr["outcome"] == "WIN")
    losses = sum(1 for tr in trades if tr["outcome"] == "LOSS")
    open_count = sum(1 for tr in trades if tr["outcome"] == "OPEN")
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
