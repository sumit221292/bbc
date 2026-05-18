"""Test the alert worker's synthetic-signal close pass.

Reproduces the production bug where the strategy stopped re-emitting at a
prior signal_time (because its rolling support/resistance window shifted),
which left the DB row stuck OPEN even after price clearly hit the stop.

The new close pass rebuilds a synthetic Signal straight from the DB row
and annotates against the live candles, independent of whether the
strategy still emits at that bar.

Run: python backend/tests/test_synthetic_resolve.py
"""
from __future__ import annotations

import os
import sys
import tempfile

TMP_DIR = tempfile.mkdtemp(prefix="btc-resolve-")
os.environ["DATA_DIR"] = TMP_DIR

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from app import trade_store
from app.schemas import Candle, Signal
from app.trade_status import annotate


def C(t, o, h, l, c, v=100.0):
    return Candle(time=t, open=o, high=h, low=l, close=c, volume=v)


def fail(msg):
    raise AssertionError(msg)


def near(a, b, tol=1e-6):
    return abs(a - b) <= tol


def synth_resolve_one(row, candles):
    """Mirrors the alerts.py close-pass logic, kept here so the test does
    not depend on importing the worker module (which pulls httpx etc)."""
    synth = Signal(
        time=row["signal_time"], type=row["type"],
        price=row["entry"], reason=row.get("reason") or "",
        entry=row["entry"], stop_loss=row["stop_loss"], target=row["target"],
    )
    return annotate([synth], candles)[0]


def scenario_strategy_silent_but_stop_hit():
    """The original bug: strategy generated a BUY signal at t=1000 but later
    its rolling indicators stopped emitting at that bar. Price subsequently
    pierced the stop. The naive close pass (which depended on the strategy
    re-emitting) would miss this. The synthetic resolver must catch it."""
    print("[1] BUY @ 100 (stop 95) -- strategy no longer emits, but bar low hit stop")
    candles = [
        C(1000, 100, 101, 99, 100),     # signal bar
        C(1060, 100, 101, 96, 99),      # close in
        C(1120, 99,  100, 94, 95),      # low pierces stop -> LOSS
        C(1180, 95,  97,  93, 96),
    ]
    trade_store.init_db()
    trade_store.insert_trade(
        strategy_id="x", interval="1h", symbol="BTCUSDT", signal_time=1000,
        type_="BUY", entry=100, stop_loss=95, target=110, reason="t",
        created_at=1000,
    )
    rows = trade_store.open_trades("x", "1h", "BTCUSDT")
    if len(rows) != 1: fail("expected 1 open row")
    resolved = synth_resolve_one(rows[0], candles)
    if resolved.status != "LOSS":
        fail(f"expected LOSS, got {resolved.status}")
    if not near(resolved.pnl_pct, -5.0):
        fail(f"expected -5.0%, got {resolved.pnl_pct}")
    print(f"    OK -- synthetic resolve correctly closed as LOSS pnl={resolved.pnl_pct:.2f}%")


def scenario_sell_target_hit_after_strategy_silent():
    print("[2] SELL @ 100 (target 90) -- strategy silent, low pierces target")
    candles = [
        C(2000, 100, 101, 99, 100),
        C(2060, 100, 102, 95, 97),
        C(2120, 97,  98,  88, 91),      # low pierces target -> WIN
    ]
    trade_store.insert_trade(
        strategy_id="y", interval="1h", symbol="BTCUSDT", signal_time=2000,
        type_="SELL", entry=100, stop_loss=105, target=90, reason="t",
        created_at=2000,
    )
    rows = trade_store.open_trades("y", "1h", "BTCUSDT")
    if len(rows) != 1: fail("expected 1 open row for y")
    resolved = synth_resolve_one(rows[0], candles)
    if resolved.status != "WIN":
        fail(f"expected WIN, got {resolved.status}")
    if not near(resolved.pnl_pct, 10.0):
        fail(f"expected +10.0%, got {resolved.pnl_pct}")
    print(f"    OK -- synthetic resolve correctly closed as WIN pnl={resolved.pnl_pct:.2f}%")


def scenario_buy_target_hit_after_strategy_silent():
    """Same bug mirror: target hit on a BUY when the strategy went silent.
    Without the fix this would have stayed OPEN forever instead of WIN."""
    print("[2b] BUY @ 100 (target 110) -- strategy silent, high pierces target")
    candles = [
        C(2500, 100, 101, 99, 100),
        C(2560, 100, 105, 99, 104),
        C(2620, 104, 112, 103, 111),    # high pierces target -> WIN
    ]
    trade_store.insert_trade(
        strategy_id="y2", interval="1h", symbol="BTCUSDT", signal_time=2500,
        type_="BUY", entry=100, stop_loss=95, target=110, reason="t",
        created_at=2500,
    )
    resolved = synth_resolve_one(trade_store.open_trades("y2", "1h", "BTCUSDT")[0], candles)
    if resolved.status != "WIN":
        fail(f"expected WIN, got {resolved.status}")
    if not near(resolved.pnl_pct, 10.0):
        fail(f"expected +10.0%, got {resolved.pnl_pct}")
    print(f"    OK -- BUY target-hit closed as WIN pnl={resolved.pnl_pct:.2f}%")


def scenario_sell_stop_hit_after_strategy_silent():
    """Fourth corner of the matrix: SELL stop hit while strategy is silent."""
    print("[2c] SELL @ 100 (stop 105) -- strategy silent, high pierces stop")
    candles = [
        C(2700, 100, 101, 99, 100),
        C(2760, 100, 103, 99, 102),
        C(2820, 102, 108, 101, 107),    # high pierces stop -> LOSS
    ]
    trade_store.insert_trade(
        strategy_id="y3", interval="1h", symbol="BTCUSDT", signal_time=2700,
        type_="SELL", entry=100, stop_loss=105, target=90, reason="t",
        created_at=2700,
    )
    resolved = synth_resolve_one(trade_store.open_trades("y3", "1h", "BTCUSDT")[0], candles)
    if resolved.status != "LOSS":
        fail(f"expected LOSS, got {resolved.status}")
    if not near(resolved.pnl_pct, -5.0):
        fail(f"expected -5.0%, got {resolved.pnl_pct}")
    print(f"    OK -- SELL stop-hit closed as LOSS pnl={resolved.pnl_pct:.2f}%")


def scenario_still_open_when_neither_hit():
    print("[3] BUY @ 100 (stop 95, target 110) -- neither hit, must stay OPEN")
    candles = [
        C(3000, 100, 101, 99, 100),
        C(3060, 100, 103, 98, 102),
        C(3120, 102, 104, 99, 103),
    ]
    trade_store.insert_trade(
        strategy_id="z", interval="1h", symbol="BTCUSDT", signal_time=3000,
        type_="BUY", entry=100, stop_loss=95, target=110, reason="t",
        created_at=3000,
    )
    rows = trade_store.open_trades("z", "1h", "BTCUSDT")
    resolved = synth_resolve_one(rows[0], candles)
    if resolved.status == "WIN" or resolved.status == "LOSS":
        fail(f"expected OPEN, got {resolved.status}")
    print(f"    OK -- OPEN preserved when neither stop nor target hit")


def scenario_all_open_trades_returns_orphans():
    """The orphan-resolve path scans all OPEN rows regardless of which
    strategies are currently subscribed. trade_store.all_open_trades()
    must therefore return rows from any strategy as long as status='OPEN'."""
    print("[5] all_open_trades() surfaces unsubscribed orphans")
    # Pretend this strategy is no longer subscribed; the row must still appear.
    trade_store.insert_trade(
        strategy_id="unsubscribed_strat", interval="1h", symbol="BTCUSDT",
        signal_time=5000, type_="BUY", entry=100, stop_loss=95, target=110,
        reason="orphan", created_at=5000,
    )
    rows = trade_store.all_open_trades()
    orphan = next((r for r in rows if r["strategy_id"] == "unsubscribed_strat"), None)
    if orphan is None:
        fail("all_open_trades() must include orphan rows")
    if orphan["status"] != "OPEN":
        fail(f"orphan should still be OPEN, got {orphan['status']}")
    # Close it via the synth-resolve path even though the strategy was never
    # subscribed/iterated.
    candles = [
        C(5000, 100, 101, 99, 100),
        C(5060, 100, 102, 94, 96),    # low pierces stop -> LOSS
    ]
    resolved = synth_resolve_one(orphan, candles)
    if resolved.status != "LOSS":
        fail(f"orphan should resolve LOSS, got {resolved.status}")
    print("    OK -- orphan trade visible and resolvable independent of subscription state")


def scenario_symbol_isolation():
    print("[4] open_trades() honours symbol filter")
    trade_store.insert_trade(
        strategy_id="multi", interval="1h", symbol="BTCUSDT", signal_time=4000,
        type_="BUY", entry=100, stop_loss=95, target=110, reason="t",
        created_at=4000,
    )
    trade_store.insert_trade(
        strategy_id="multi", interval="1h", symbol="ETHUSDT", signal_time=4001,
        type_="BUY", entry=2000, stop_loss=1900, target=2200, reason="t",
        created_at=4001,
    )
    btc = trade_store.open_trades("multi", "1h", "BTCUSDT")
    eth = trade_store.open_trades("multi", "1h", "ETHUSDT")
    if len(btc) != 1 or btc[0]["symbol"] != "BTCUSDT":
        fail(f"BTC partition leaked: {btc}")
    if len(eth) != 1 or eth[0]["symbol"] != "ETHUSDT":
        fail(f"ETH partition leaked: {eth}")
    print("    OK -- BTC and ETH rows isolated by symbol filter")


def main():
    print(f"DB at: {trade_store.DB_PATH}")
    try:
        # Full 4-corner matrix of (BUY/SELL) x (stop hit / target hit)
        # to prove the strategy-silent close path resolves them all.
        scenario_strategy_silent_but_stop_hit()           # BUY -> LOSS
        scenario_sell_target_hit_after_strategy_silent()  # SELL -> WIN
        scenario_buy_target_hit_after_strategy_silent()   # BUY -> WIN
        scenario_sell_stop_hit_after_strategy_silent()    # SELL -> LOSS
        scenario_still_open_when_neither_hit()
        scenario_all_open_trades_returns_orphans()
        scenario_symbol_isolation()
        print("\nALL 7 SCENARIOS PASSED")
        return 0
    except AssertionError as e:
        print(f"\nFAIL: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
