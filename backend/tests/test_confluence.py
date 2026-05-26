"""Unit tests for the Confluence meta-strategy.

We don't drive real market data through the full panel here -- that
would be a backtest. Instead we test the VOTING + AGGREGATION logic
directly by stubbing the voter list with controlled fixtures.

Run: python backend/tests/test_confluence.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from app.schemas import Candle, Signal
from app.strategies.base import Strategy
from app.strategies.confluence import Confluence


def C(t, c, h=None, l=None):
    h = h if h is not None else c + 1
    l = l if l is not None else c - 1
    return Candle(time=t, open=c, high=h, low=l, close=c, volume=1.0)


def fail(msg):
    raise AssertionError(msg)


def near(a, b, tol=0.01):
    return abs(a - b) <= tol


# --- Test fixtures: stub voter classes ---

def make_voter(voter_id, signals_at):
    """Build a Strategy subclass that returns a fixed signal list."""
    # Capture into locals so the class body sees them by attribute, not by
    # closure (class bodies don't reach enclosing scope for assignments).
    _id_val = voter_id
    _sigs = list(signals_at)
    class _Stub(Strategy):
        id = _id_val
        name = _id_val
        description = "test stub"
        def evaluate(self, candles):
            return list(_sigs)
    _Stub.__name__ = f"Stub_{voter_id}"
    return _Stub


# 60 candles spaced 1h apart, prices climbing gently.
TIMES = [1_000_000 + i * 3600 for i in range(60)]
CANDLES = [C(t, 100 + i * 0.1) for i, t in enumerate(TIMES)]
BAR_T = TIMES[50]   # the bar where the test setups fire


def sig(side, t, entry=100, stop=None, target=None):
    # Default RR = 2.0 exactly (risk 1, reward 2) so the global RR floor
    # passes after median aggregation, just like real strategies do.
    if side == "BUY":
        stop = stop if stop is not None else entry - 1.0
        target = target if target is not None else entry + 2.0
    else:
        stop = stop if stop is not None else entry + 1.0
        target = target if target is not None else entry - 2.0
    return Signal(time=t, type=side, price=entry, reason="stub",
                  entry=entry, stop_loss=stop, target=target)


def run_confluence(voters, candles=CANDLES, min_votes=None):
    """Patch Confluence.VOTERS and evaluate."""
    c = Confluence()
    c.VOTERS = tuple(voters)
    if min_votes is not None:
        c.MIN_VOTES = min_votes
    return c.evaluate(candles)


# ---------- Test scenarios ----------

def test_no_signals_when_below_threshold():
    print("[1] Only 2 voters agree -- below MIN_VOTES=3 -> no signal")
    voters = [
        make_voter("a", [sig("BUY", BAR_T)]),
        make_voter("b", [sig("BUY", BAR_T)]),
        make_voter("c", []),
    ]
    out = run_confluence(voters)
    if out:
        fail(f"expected no signals, got {out}")
    print("    OK")


def test_signal_fires_when_threshold_met():
    print("[2] 3 voters agree on BUY -> Confluence fires BUY")
    # Each voter has its own RR=2 setup; medians should still clear the
    # router's 1:2 RR floor.
    voters = [
        make_voter("a", [sig("BUY", BAR_T, entry=100, stop=99, target=102)]),
        make_voter("b", [sig("BUY", BAR_T, entry=101, stop=100, target=103)]),
        make_voter("c", [sig("BUY", BAR_T, entry=102, stop=101, target=104)]),
    ]
    out = run_confluence(voters)
    if not out:
        fail("expected at least one signal")
    s = out[0]
    if s.type != "BUY":
        fail(f"expected BUY, got {s.type}")
    # Median across all three (101, 100, 103).
    if not near(s.entry, 101):
        fail(f"entry should be median 101, got {s.entry}")
    if not near(s.stop_loss, 100):
        fail(f"stop should be median 100, got {s.stop_loss}")
    if not near(s.target, 103):
        fail(f"target should be median 103, got {s.target}")
    print(f"    OK -- entry={s.entry} stop={s.stop_loss} target={s.target}")
    print(f"           reason: {s.reason}")


def test_mixed_votes_dont_fire():
    print("[3] 2 BUY + 2 SELL same bar -> ambiguous, no signal")
    voters = [
        make_voter("a", [sig("BUY", BAR_T)]),
        make_voter("b", [sig("BUY", BAR_T)]),
        make_voter("c", [sig("SELL", BAR_T)]),
        make_voter("d", [sig("SELL", BAR_T)]),
    ]
    out = run_confluence(voters)
    if out:
        fail(f"expected no signal for tied votes, got {out}")
    print("    OK")


def test_majority_wins():
    print("[4] 3 BUY + 1 SELL -> BUY wins")
    voters = [
        make_voter("a", [sig("BUY", BAR_T)]),
        make_voter("b", [sig("BUY", BAR_T)]),
        make_voter("c", [sig("BUY", BAR_T)]),
        make_voter("d", [sig("SELL", BAR_T)]),
    ]
    out = run_confluence(voters)
    if not out or out[0].type != "BUY":
        fail(f"expected BUY, got {out}")
    print("    OK")


def test_window_clusters_adjacent_bars():
    """Two voters at bar T and one at bar T+1 should still cluster
    into a single 3-vote event because VOTE_WINDOW_BARS=2."""
    print("[5] Votes spread across 2 adjacent bars still cluster")
    bar_T = TIMES[50]
    bar_T1 = TIMES[51]
    voters = [
        make_voter("a", [sig("BUY", bar_T)]),
        make_voter("b", [sig("BUY", bar_T)]),
        make_voter("c", [sig("BUY", bar_T1)]),
    ]
    out = run_confluence(voters)
    if not out:
        fail("expected signal from windowed votes")
    print(f"    OK -- {out[0].reason}")


def test_rr_floor_rejects_low_quality():
    print("[6] Votes with RR < 1:2 are rejected even if 3+ agree")
    # Entry 100, stop 99 (risk 1), target 101.5 (reward 1.5) -> RR 1.5 < 2.0
    voters = [
        make_voter("a", [sig("BUY", BAR_T, entry=100, stop=99, target=101.5)]),
        make_voter("b", [sig("BUY", BAR_T, entry=100, stop=99, target=101.5)]),
        make_voter("c", [sig("BUY", BAR_T, entry=100, stop=99, target=101.5)]),
    ]
    out = run_confluence(voters)
    if out:
        fail(f"expected RR floor to drop, got {out}")
    print("    OK")


def test_no_cooldown_emits_each_qualifying_bar():
    print("[7] COOLDOWN_BARS=0 -- consecutive bars both emit (trail downstream)")
    # Three voters all firing at bar T and again at bar T+1. With cooldown
    # disabled, each qualifying bar fires; the worker's ratchet-trail path
    # turns the T+1 emit into a SL/TP update on the existing OPEN trade
    # instead of a duplicate position. Confluence itself should emit twice.
    bar_T = TIMES[50]
    bar_T1 = TIMES[51]
    voters = [
        make_voter("a", [sig("BUY", bar_T), sig("BUY", bar_T1)]),
        make_voter("b", [sig("BUY", bar_T), sig("BUY", bar_T1)]),
        make_voter("c", [sig("BUY", bar_T), sig("BUY", bar_T1)]),
    ]
    out = run_confluence(voters)
    # With cooldown=4 the old code emitted exactly 1. With cooldown=0 the
    # sliding window keeps qualifying for every bar the votes stay inside
    # VOTE_WINDOW_BARS, so we get >=2 emissions. The exact count depends
    # on the window size + how many bars the votes span -- the point is
    # only that suppression has lifted.
    if len(out) < 2:
        fail(f"expected >=2 signals (no cooldown), got {len(out)}: {out}")
    print(f"    OK -- {len(out)} emits, downstream trails everything past the 1st")


def main():
    try:
        test_no_signals_when_below_threshold()
        test_signal_fires_when_threshold_met()
        test_mixed_votes_dont_fire()
        test_majority_wins()
        test_window_clusters_adjacent_bars()
        test_rr_floor_rejects_low_quality()
        test_no_cooldown_emits_each_qualifying_bar()
        print("\nALL 7 CONFLUENCE TESTS PASSED")
        return 0
    except AssertionError as e:
        print(f"\nFAIL: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
