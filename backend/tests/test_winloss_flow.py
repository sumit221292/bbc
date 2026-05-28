"""End-to-end correctness check for the alert worker's win/loss path.

Builds a synthetic candle sequence + signal, runs the EXACT pipeline the
alert_loop uses (annotate -> trade_store.insert -> trade_store.close ->
trade_store.stats), and asserts the resulting numbers match the math we
quote in the Telegram closure message.

Run with: python backend/tests/test_winloss_flow.py
"""
from __future__ import annotations

import os
import sys
import tempfile

# Point trade_store at a throwaway DB before importing anything that uses it.
TMP_DIR = tempfile.mkdtemp(prefix="btc-winloss-")
os.environ["DATA_DIR"] = TMP_DIR

# Make the app package importable when run from repo root.
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from app import trade_store
from app.schemas import Candle, Signal
from app.trade_status import annotate


def make_candle(t: int, o: float, h: float, low: float, c: float) -> Candle:
    return Candle(time=t, open=o, high=h, low=low, close=c, volume=1.0)


def fail(msg: str) -> None:
    raise AssertionError(msg)


def near(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def scenario_buy_win() -> None:
    """BUY @ 100, stop 95, target 110 -> later candle hits 111 -> WIN +10%."""
    print("\n[1] BUY -> WIN")
    candles = [
        make_candle(1000, 100, 101, 99, 100),  # signal bar
        make_candle(1060, 100, 105, 99, 104),  # going up
        make_candle(1120, 104, 111, 103, 110),  # target hit at 111
    ]
    sig = Signal(time=1000, type="BUY", price=100, reason="test", entry=100, stop_loss=95, target=110)
    annotated = annotate([sig], candles)[0]
    if annotated.status != "WIN":
        fail(f"expected WIN, got {annotated.status}")
    if not near(annotated.pnl_pct, 10.0):
        fail(f"expected pnl 10.0%, got {annotated.pnl_pct}")
    if annotated.closed_at != 1120:
        fail(f"expected closed_at=1120, got {annotated.closed_at}")

    # Worker path: insert OPEN, then close on the same evaluation.
    trade_store.insert_trade(
        strategy_id="x", interval="1h", symbol="BTCUSDT",
        signal_time=1000, type_="BUY", entry=100, stop_loss=95, target=110,
        reason="test", created_at=1000,
    )
    trade_store.close_trade(
        strategy_id="x", interval="1h", symbol="BTCUSDT", signal_time=1000,
        status="WIN", exit_price=110, exit_time=1120, pnl_pct=10.0,
    )
    rows = trade_store.list_trades(strategy_id="x", interval="1h")
    if len(rows) != 1: fail("expected 1 row")
    r = rows[0]
    if r["status"] != "WIN": fail(f"row status {r['status']}")
    if not near(r["pnl_pct"], 10.0): fail(f"row pnl_pct {r['pnl_pct']}")
    if not near(r["exit_price"], 110.0): fail(f"row exit_price {r['exit_price']}")

    s = trade_store.stats(strategy_id="x", interval="1h")
    if s["wins"] != 1 or s["losses"] != 0: fail(f"stats wrong: {s}")
    if not near(s["win_rate"], 100.0): fail(f"win_rate {s['win_rate']}")
    if not near(s["total_pnl_pct"], 10.0): fail(f"total_pnl {s['total_pnl_pct']}")
    print("    OK -- WIN pnl=+10.0% stats={wins:1, losses:0, win_rate:100%}")


def scenario_buy_loss() -> None:
    """BUY @ 100, stop 95, target 110 -> later candle hits 94 -> LOSS -5%."""
    print("\n[2] BUY -> LOSS")
    candles = [
        make_candle(2000, 100, 101, 99, 100),
        make_candle(2060, 100, 102, 94, 96),  # low pierces stop
    ]
    sig = Signal(time=2000, type="BUY", price=100, reason="test", entry=100, stop_loss=95, target=110)
    annotated = annotate([sig], candles)[0]
    if annotated.status != "LOSS": fail(f"expected LOSS, got {annotated.status}")
    if not near(annotated.pnl_pct, -5.0): fail(f"expected -5.0%, got {annotated.pnl_pct}")

    trade_store.insert_trade(
        strategy_id="x", interval="1h", symbol="BTCUSDT",
        signal_time=2000, type_="BUY", entry=100, stop_loss=95, target=110,
        reason="test", created_at=2000,
    )
    trade_store.close_trade(
        strategy_id="x", interval="1h", symbol="BTCUSDT", signal_time=2000,
        status="LOSS", exit_price=95, exit_time=2060, pnl_pct=-5.0,
    )
    s = trade_store.stats(strategy_id="x", interval="1h")
    if s["wins"] != 1 or s["losses"] != 1: fail(f"stats {s}")
    # After 1 win (+10) + 1 loss (-5): total = +5, win_rate = 50%
    if not near(s["total_pnl_pct"], 5.0): fail(f"total {s['total_pnl_pct']}")
    if not near(s["win_rate"], 50.0): fail(f"win_rate {s['win_rate']}")
    print("    OK -- LOSS pnl=-5.0% rolling stats={1W,1L, total=+5%, win_rate=50%}")


def scenario_sell_win() -> None:
    """SELL @ 100, stop 105, target 90 -> later candle drops to 89 -> WIN +10%."""
    print("\n[3] SELL -> WIN")
    candles = [
        make_candle(3000, 100, 101, 99, 100),
        make_candle(3060, 100, 100, 89, 92),  # low pierces target
    ]
    sig = Signal(time=3000, type="SELL", price=100, reason="test", entry=100, stop_loss=105, target=90)
    annotated = annotate([sig], candles)[0]
    if annotated.status != "WIN": fail(f"expected WIN, got {annotated.status}")
    if not near(annotated.pnl_pct, 10.0): fail(f"expected +10.0%, got {annotated.pnl_pct}")
    print("    OK -- SELL WIN pnl=+10.0% (entry 100, target 90)")


def scenario_sell_loss() -> None:
    """SELL @ 100, stop 105, target 90 -> later candle spikes to 106 -> LOSS -5%."""
    print("\n[4] SELL -> LOSS")
    candles = [
        make_candle(4000, 100, 101, 99, 100),
        make_candle(4060, 100, 106, 99, 103),  # high pierces stop
    ]
    sig = Signal(time=4000, type="SELL", price=100, reason="test", entry=100, stop_loss=105, target=90)
    annotated = annotate([sig], candles)[0]
    if annotated.status != "LOSS": fail(f"expected LOSS, got {annotated.status}")
    if not near(annotated.pnl_pct, -5.0): fail(f"expected -5.0%, got {annotated.pnl_pct}")
    print("    OK -- SELL LOSS pnl=-5.0% (entry 100, stop 105)")


def scenario_open_no_resolution() -> None:
    """BUY but neither stop nor target hit -> OPEN with mark-to-market PnL."""
    print("\n[5] OPEN (neither hit)")
    candles = [
        make_candle(5000, 100, 101, 99, 100),
        make_candle(5060, 100, 104, 98, 103),  # ranges inside, neither extreme
    ]
    sig = Signal(time=5000, type="BUY", price=100, reason="test", entry=100, stop_loss=95, target=110)
    annotated = annotate([sig], candles)[0]
    if annotated.status != "OPEN": fail(f"expected OPEN, got {annotated.status}")
    # mark-to-market = (last_close - entry) / entry * 100 = (103-100)/100 = 3%
    if not near(annotated.pnl_pct, 3.0): fail(f"expected mtm 3.0%, got {annotated.pnl_pct}")
    print("    OK -- OPEN mtm=+3.0% (last close 103, entry 100)")


def scenario_partition_isolation() -> None:
    """Stats grouped by (strategy_id, interval) must NOT mix partitions."""
    print("\n[6] Partition isolation (strategy + interval)")
    trade_store.insert_trade(
        strategy_id="champion", interval="5m", symbol="BTCUSDT",
        signal_time=6000, type_="BUY", entry=100, stop_loss=95, target=110,
        reason="test", created_at=6000,
    )
    trade_store.close_trade(
        strategy_id="champion", interval="5m", symbol="BTCUSDT", signal_time=6000,
        status="WIN", exit_price=110, exit_time=6060, pnl_pct=10.0,
    )
    trade_store.insert_trade(
        strategy_id="champion", interval="1h", symbol="BTCUSDT",
        signal_time=6000, type_="BUY", entry=200, stop_loss=190, target=220,
        reason="test", created_at=6000,
    )
    trade_store.close_trade(
        strategy_id="champion", interval="1h", symbol="BTCUSDT", signal_time=6000,
        status="LOSS", exit_price=190, exit_time=6060, pnl_pct=-5.0,
    )
    s5 = trade_store.stats(strategy_id="champion", interval="5m")
    s1h = trade_store.stats(strategy_id="champion", interval="1h")
    if not (s5["wins"] == 1 and s5["losses"] == 0 and near(s5["total_pnl_pct"], 10.0)):
        fail(f"5m partition wrong: {s5}")
    if not (s1h["wins"] == 0 and s1h["losses"] == 1 and near(s1h["total_pnl_pct"], -5.0)):
        fail(f"1h partition wrong: {s1h}")
    print(f"    OK -- champion 5m: +10% (1W), champion 1h: -5% (1L) -- partitions isolated")


def scenario_dedupe() -> None:
    """Same (strategy, interval, signal_time) must INSERT OR IGNORE."""
    print("\n[7] Insert dedupe (worker re-fire safety)")
    inserted_first = trade_store.insert_trade(
        strategy_id="dup", interval="1h", symbol="BTCUSDT",
        signal_time=7000, type_="BUY", entry=100, stop_loss=95, target=110,
        reason="test", created_at=7000,
    )
    inserted_again = trade_store.insert_trade(
        strategy_id="dup", interval="1h", symbol="BTCUSDT",
        signal_time=7000, type_="BUY", entry=999, stop_loss=998, target=1000,
        reason="changed values", created_at=7100,
    )
    if not inserted_first: fail("first insert failed")
    if inserted_again: fail("dup insert should have been ignored")
    rows = trade_store.list_trades(strategy_id="dup", interval="1h")
    if len(rows) != 1: fail(f"expected 1 row, got {len(rows)}")
    if not near(rows[0]["entry"], 100): fail("original values overwritten!")
    print(f"    OK -- duplicate insert ignored, original values preserved")


def scenario_close_idempotency() -> None:
    """close_trade on an already-closed row must be a no-op (no flipping)."""
    print("\n[8] Close idempotency")
    trade_store.insert_trade(
        strategy_id="idem", interval="1h", symbol="BTCUSDT",
        signal_time=8000, type_="BUY", entry=100, stop_loss=95, target=110,
        reason="test", created_at=8000,
    )
    first = trade_store.close_trade(
        strategy_id="idem", interval="1h", symbol="BTCUSDT", signal_time=8000,
        status="WIN", exit_price=110, exit_time=8060, pnl_pct=10.0,
    )
    second = trade_store.close_trade(
        strategy_id="idem", interval="1h", symbol="BTCUSDT", signal_time=8000,
        status="LOSS", exit_price=95, exit_time=8120, pnl_pct=-5.0,
    )
    if not first: fail("first close should succeed")
    if second: fail("second close should have been a no-op")
    rows = trade_store.list_trades(strategy_id="idem", interval="1h")
    if rows[0]["status"] != "WIN" or not near(rows[0]["pnl_pct"], 10.0):
        fail(f"closed row should still be WIN +10%, got {rows[0]}")
    print(f"    OK -- closed row not overwritten by later close attempt")


def main() -> int:
    print(f"DB at: {trade_store.DB_PATH}")
    trade_store.init_db()
    try:
        scenario_buy_win()
        scenario_buy_loss()
        scenario_sell_win()
        scenario_sell_loss()
        scenario_open_no_resolution()
        scenario_partition_isolation()
        scenario_dedupe()
        scenario_close_idempotency()
        print("\nALL 8 SCENARIOS PASSED")
        return 0
    except AssertionError as e:
        print(f"\nFAIL: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
