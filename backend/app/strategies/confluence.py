"""Confluence — votes across the surviving profitable single-TF strategies.

Production data on 1741 worker-fired trades flagged a clear pattern:
  donchian   +36.80% PnL  44% WR  99 trades
  supertrend +23.46% PnL  50% WR  52 trades
  stochastic +15.46% PnL  36% WR  239 trades
  price_action +7.10% PnL 18% WR 139 trades   (low WR rescued by 1:3+ RR)
  adx_trend  +5.73% PnL   33% WR  19 trades

Each one has a real edge. They also fire INDEPENDENTLY -- a noisy bar
might trigger one of them by coincidence, but rarely three at once in
the same direction. We can use that property: fire only when MIN_VOTES
of the panel agree on direction at the same bar. Expected effects:

  * Win rate climbs sharply (only "obvious" setups survive the vote)
  * Trade count drops by a factor of ~5-10x (selective filter)
  * False positives are filtered out without giving up the edge

Entry / stop / target are aggregated as the MEDIAN across voters --
robust to a single outlier voter mis-pricing the setup.
"""
from __future__ import annotations

from statistics import median

from ..schemas import Candle, Signal
from .adx_trend import ADXTrend
from .base import Strategy
from .donchian_turtle import DonchianTurtle
from .price_action import PriceAction
from .stochastic_rev import StochasticReversal
from .supertrend_flip import SuperTrendFlip


class Confluence(Strategy):
    id = "confluence"
    name = "🎯 Confluence (3+ strategies agree)"
    description = (
        "Votes across the 5 profitable single-TF strategies (Donchian, "
        "SuperTrend, Stochastic, Price Action, ADX Trend). Fires only "
        "when at least 3 of the 5 agree on BUY or SELL at the same bar. "
        "Entry / stop / target are the median across the agreeing voters. "
        "Lower trade frequency, higher hit rate."
    )

    # 1h is the worker's universal storage TF. Confluence inherits that
    # so its DB rows partition cleanly alongside the voters.
    storage_interval = "1h"

    # The five strategies we trust the most after the data review.
    # Stored as classes so we can lazy-instantiate per evaluate() call.
    VOTERS: tuple[type[Strategy], ...] = (
        DonchianTurtle,
        SuperTrendFlip,
        StochasticReversal,
        PriceAction,
        ADXTrend,
    )

    MIN_VOTES = 3       # at least this many voters must agree
    COOLDOWN_BARS = 4   # avoid stacking signals on consecutive bars
    # Cluster voter signals that fire within this many bars of each other
    # into a single confluence event. Without this a Donchian BUY at bar T
    # and a SuperTrend BUY at bar T+1 would be treated as independent
    # vote-of-1s instead of a single vote-of-2.
    VOTE_WINDOW_BARS = 2

    def evaluate(self, candles: list[Candle]) -> list[Signal]:
        if len(candles) < 50:
            return []

        # Collect every voter's signals tagged with the voter's id, so the
        # output's reason field lists which strategies actually agreed.
        all_votes: list[tuple[Signal, str]] = []
        for voter_cls in self.VOTERS:
            try:
                voter_signals = voter_cls().evaluate(candles)
            except Exception:
                # A single voter blowing up should not break the meta-strategy.
                continue
            for sig in voter_signals:
                if sig.entry is None or sig.stop_loss is None or sig.target is None:
                    continue
                if sig.type not in ("BUY", "SELL"):
                    continue
                all_votes.append((sig, voter_cls.id))

        if not all_votes:
            return []

        # Sort all votes chronologically, then sweep a window. At every
        # bar in the candle list, look at all votes whose time falls
        # within [bar.time - window, bar.time]; if MIN_VOTES voters in
        # that window agree on direction, that's a confluence event.
        all_votes.sort(key=lambda x: x[0].time)
        # Indexable view of candle times to fold the window onto.
        times = [c.time for c in candles]
        out: list[Signal] = []
        last_emit_idx = -10**9
        # Pre-compute the seconds-per-bar from candle spacing.
        if len(times) >= 2:
            bar_seconds = times[1] - times[0]
        else:
            bar_seconds = 3600
        window_seconds = bar_seconds * self.VOTE_WINDOW_BARS

        # For each candle, find votes whose time is in [t - window, t].
        # Linear scan with a pointer for the lower bound -- O(n + v).
        lo = 0
        for i, t in enumerate(times):
            if i - last_emit_idx < self.COOLDOWN_BARS:
                continue
            # Advance lo until votes[lo].time >= t - window_seconds.
            while lo < len(all_votes) and all_votes[lo][0].time < t - window_seconds:
                lo += 1
            # All votes with index in [lo, hi) are in the window.
            hi = lo
            while hi < len(all_votes) and all_votes[hi][0].time <= t:
                hi += 1
            if hi - lo < self.MIN_VOTES:
                continue

            window_votes = all_votes[lo:hi]
            buys = [v for v in window_votes if v[0].type == "BUY"]
            sells = [v for v in window_votes if v[0].type == "SELL"]

            # Each voter only counts once per side per window so a single
            # voter firing twice in 2 bars does not over-count.
            buy_voters = {v[1] for v in buys}
            sell_voters = {v[1] for v in sells}

            picked = None
            if len(buy_voters) >= self.MIN_VOTES and len(buy_voters) > len(sell_voters):
                picked = ("BUY", buys, buy_voters)
            elif len(sell_voters) >= self.MIN_VOTES and len(sell_voters) > len(buy_voters):
                picked = ("SELL", sells, sell_voters)

            if picked is None:
                continue

            side, sigs, voters = picked
            entries = [s[0].entry for s in sigs]
            stops = [s[0].stop_loss for s in sigs]
            targets = [s[0].target for s in sigs]

            # Median across voters for entry, stop, AND target. Mixing
            # min/max for stop/target felt "safer" but in practice it
            # combines the worst-risk voter's stop with the best-reward
            # voter's target -- the resulting RR can collapse below the
            # 2.0 floor even when every voter individually clears it.
            # Median is the central tendency and preserves the RR of a
            # well-behaved panel.
            entry_px = median(entries)
            stop_px = median(stops)
            target_px = median(targets)

            # Reject if RR collapsed below the global 1:2 floor that the
            # router enforces anyway -- saves a wasted insert.
            risk = abs(entry_px - stop_px)
            if risk <= 0:
                continue
            reward = abs(target_px - entry_px)
            if reward / risk < 2.0:
                continue

            reason = (
                f"Confluence {side}: {len(voters)} voters agreed -- "
                + ", ".join(sorted(voters))
            )
            out.append(Signal(
                time=t, type=side, price=candles[i].close,
                reason=reason,
                entry=entry_px, stop_loss=stop_px, target=target_px,
            ))
            last_emit_idx = i

        return out
