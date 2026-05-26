"""SQLite persistence for the BTC app.

Two tables, both narrow:
  trades    -- one row per live alert signal (insert at fire time, flip
               OPEN->WIN/LOSS when candles resolve it). Backtest data never
               lands here. Unique on (strategy_id, interval, signal_time).

  kv_store  -- (key, value) singletons. value is a JSON string. Used for the
               alert config blob so Telegram setup, subscriptions, auto-trade
               settings, current position, and daily counters all live in one
               place and survive Railway redeploys (when /data is a volume).

Storage path: ${DATA_DIR}/app.db. DATA_DIR defaults to /data when that path
exists and is writable (Railway volume convention), else falls back to the
backend folder for local dev.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any


def _resolve_data_dir() -> Path:
    """Pick a writable directory for the DB. Honors DATA_DIR for explicit
    overrides; otherwise prefers /data (Railway volume) when it exists,
    falling back to the backend package directory."""
    override = os.environ.get("DATA_DIR")
    if override:
        p = Path(override)
        p.mkdir(parents=True, exist_ok=True)
        return p
    railway_volume = Path("/data")
    if railway_volume.exists() and os.access(railway_volume, os.W_OK):
        return railway_volume
    # Local dev fallback: backend/ next to this module's parent.
    return Path(__file__).resolve().parent.parent


DATA_DIR = _resolve_data_dir()
DB_PATH = DATA_DIR / "app.db"

# sqlite3 connections aren't safe to share across threads without a lock.
# FastAPI runs request handlers in a threadpool, so guard every call.
_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _lock, _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy_id TEXT NOT NULL,
                interval    TEXT NOT NULL,
                symbol      TEXT NOT NULL,
                signal_time INTEGER NOT NULL,
                type        TEXT NOT NULL,
                entry       REAL NOT NULL,
                stop_loss   REAL NOT NULL,
                target      REAL NOT NULL,
                status      TEXT NOT NULL DEFAULT 'OPEN',
                exit_price  REAL,
                exit_time   INTEGER,
                pnl_pct     REAL,
                reason      TEXT,
                created_at  INTEGER NOT NULL,
                UNIQUE(strategy_id, interval, symbol, signal_time)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_trades_strat_interval "
            "ON trades(strategy_id, interval, signal_time DESC)"
        )
        # Schema migration: the original UNIQUE constraint was
        # (strategy_id, interval, signal_time) -- symbol was missing.
        # On 1h bars the close time is identical across coins, so the
        # second-arriving INSERT for the same strategy + interval +
        # signal_time hit a UNIQUE violation and was silently dropped
        # (INSERT OR IGNORE). Result: only the first coin's signal was
        # ever persisted at any given bar close. We detect the old
        # constraint via PRAGMA index_list and, if found, rebuild the
        # table with the correct constraint. Done on every boot so the
        # migration runs once and then becomes a no-op.
        idx_rows = conn.execute("PRAGMA index_list('trades')").fetchall()
        needs_migration = False
        for ix in idx_rows:
            if ix["unique"]:
                cols = [r["name"] for r in
                        conn.execute(f"PRAGMA index_info('{ix['name']}')").fetchall()]
                # Old (broken) constraint: 3 cols, no 'symbol'.
                if "symbol" not in cols and len(cols) == 3:
                    needs_migration = True
                    break
        if needs_migration:
            import logging as _log
            _log.getLogger("btc").info(
                "[trade_store] Migrating trades table: adding symbol to UNIQUE constraint"
            )
            conn.executescript("""
                BEGIN;
                CREATE TABLE trades_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_id TEXT NOT NULL,
                    interval    TEXT NOT NULL,
                    symbol      TEXT NOT NULL,
                    signal_time INTEGER NOT NULL,
                    type        TEXT NOT NULL,
                    entry       REAL NOT NULL,
                    stop_loss   REAL NOT NULL,
                    target      REAL NOT NULL,
                    status      TEXT NOT NULL DEFAULT 'OPEN',
                    exit_price  REAL,
                    exit_time   INTEGER,
                    pnl_pct     REAL,
                    reason      TEXT,
                    created_at  INTEGER NOT NULL,
                    UNIQUE(strategy_id, interval, symbol, signal_time)
                );
                INSERT INTO trades_new SELECT * FROM trades;
                DROP TABLE trades;
                ALTER TABLE trades_new RENAME TO trades;
                CREATE INDEX IF NOT EXISTS idx_trades_strat_interval
                    ON trades(strategy_id, interval, signal_time DESC);
                COMMIT;
            """)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS kv_store (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        conn.commit()

    # One-shot trade history wipe (May 2026). The user asked to start
    # fresh after the sub-$1 dropdown filter shipped; without a clean
    # slate the pre-filter PEPE/SHIB/DOGE trade rows would keep
    # polluting the Trades tab and the chip-stat win-rates forever.
    # A kv_store marker ensures this fires exactly once per deploy
    # lineage -- subsequent restarts see the marker and become no-ops.
    _maybe_one_shot_wipe()


def _maybe_one_shot_wipe() -> None:
    """Idempotent trade-history reset, gated by a kv marker. Re-bump the
    marker name (append a new date) to fire another wipe in the future."""
    import logging as _log
    import time as _t
    # Bumped 2026-05-26: previous run accumulated corrupted rows because
    # close_trade / update_trade_levels were missing the symbol filter,
    # so every coin's trade at a given signal_time was closed with one
    # coin's exit_price (LTC inheriting BTC's 76k price, etc.). After
    # this commit fixes the SQL, the historical garbage must be wiped
    # so the summaries don't keep showing 49,000%+ cumulative PnL.
    marker = "trades_wiped_2026_05_26_crosscoin_bug"
    log = _log.getLogger("btc")
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT value FROM kv_store WHERE key = ?", (marker,),
        ).fetchone()
        if row is not None:
            return  # already wiped on a previous boot
        cur = conn.execute("DELETE FROM trades")
        n = cur.rowcount
        conn.execute(
            "INSERT INTO kv_store (key, value, updated_at) VALUES (?, ?, ?)",
            (marker, json.dumps({"wiped": n, "at": int(_t.time())}), int(_t.time())),
        )
        conn.commit()
        log.info("[trade_store] one-shot wipe fired: removed %d trade rows", n)


# ---------- Key-value (singleton blobs) ----------

def get_kv(key: str) -> Any | None:
    """Return the JSON-decoded value for `key`, or None if missing/corrupt."""
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT value FROM kv_store WHERE key = ?", (key,)
        ).fetchone()
    if row is None:
        return None
    try:
        return json.loads(row["value"])
    except json.JSONDecodeError:
        return None


def set_kv(key: str, value: Any, *, now: int | None = None) -> None:
    import time as _t
    ts = int(_t.time()) if now is None else now
    payload = json.dumps(value, default=str)
    with _lock, _connect() as conn:
        conn.execute(
            """
            INSERT INTO kv_store (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, payload, ts),
        )
        conn.commit()


def delete_kv(key: str) -> bool:
    with _lock, _connect() as conn:
        cur = conn.execute("DELETE FROM kv_store WHERE key = ?", (key,))
        conn.commit()
        return cur.rowcount > 0


def insert_trade(
    *,
    strategy_id: str,
    interval: str,
    symbol: str,
    signal_time: int,
    type_: str,
    entry: float,
    stop_loss: float,
    target: float,
    reason: str = "",
    created_at: int,
) -> bool:
    """Insert a brand-new OPEN trade. Returns True if a row was inserted,
    False if (strategy_id, interval, signal_time) was already there."""
    with _lock, _connect() as conn:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO trades
                (strategy_id, interval, symbol, signal_time, type,
                 entry, stop_loss, target, status, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?)
            """,
            (
                strategy_id, interval, symbol, signal_time, type_,
                entry, stop_loss, target, reason, created_at,
            ),
        )
        conn.commit()
        return cur.rowcount > 0


def update_trade_levels(
    *,
    strategy_id: str,
    interval: str,
    symbol: str,
    signal_time: int,
    stop_loss: float,
    target: float,
) -> bool:
    """Move an OPEN trade's SL and TP to new values. Used by the
    ratchet-trail path in alert_loop -- a same-direction signal at a
    later bar shifts the existing trade's protection inward (BUY: SL up,
    TP up) instead of opening a duplicate position. Caller is
    responsible for enforcing the ratchet rule (never widen the stop).
    Returns True if a row was updated, False if the trade is already
    closed or never existed.

    Filters by symbol for the same reason close_trade does -- 1h bar
    close times collide across coins, so omitting symbol would trail
    every coin's same-signal_time trade with one symbol's new levels."""
    with _lock, _connect() as conn:
        cur = conn.execute(
            """
            UPDATE trades
               SET stop_loss = ?, target = ?
             WHERE strategy_id = ? AND interval = ? AND symbol = ?
               AND signal_time = ? AND status = 'OPEN'
            """,
            (stop_loss, target, strategy_id, interval, symbol, signal_time),
        )
        conn.commit()
        return cur.rowcount > 0


def close_trade(
    *,
    strategy_id: str,
    interval: str,
    symbol: str,
    signal_time: int,
    status: str,        # WIN or LOSS
    exit_price: float,
    exit_time: int,
    pnl_pct: float,
) -> bool:
    """Flip an OPEN row to its final WIN/LOSS state. No-op if already closed.

    CRITICAL: must filter by symbol. 1h bar close times are identical
    across coins, so without the symbol predicate one BTC trade closing
    at signal_time=T also closes every other coin's OPEN trade at T --
    inheriting BTC's exit_price + pnl_pct. That bug produced
    +12,362% pnl_pct rows on LTC / XRP / ZEC when BTC stopped out, and
    a +49,181% cumulative summary visible in the Trades tab."""
    if status not in ("WIN", "LOSS"):
        return False
    with _lock, _connect() as conn:
        cur = conn.execute(
            """
            UPDATE trades
               SET status = ?, exit_price = ?, exit_time = ?, pnl_pct = ?
             WHERE strategy_id = ? AND interval = ? AND symbol = ?
               AND signal_time = ? AND status = 'OPEN'
            """,
            (status, exit_price, exit_time, pnl_pct,
             strategy_id, interval, symbol, signal_time),
        )
        conn.commit()
        return cur.rowcount > 0


def all_open_trades() -> list[dict[str, Any]]:
    """Every OPEN row across strategies / intervals / symbols. The worker's
    global resolve pass uses this so an open trade is never abandoned --
    even after the user unsubscribes from the strategy that fired it."""
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM trades WHERE status = 'OPEN' ORDER BY signal_time ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def open_trades(strategy_id: str, interval: str, symbol: str | None = None) -> list[dict[str, Any]]:
    sql = ("SELECT * FROM trades WHERE strategy_id = ? AND interval = ? "
           "AND status = 'OPEN'")
    params: list[Any] = [strategy_id, interval]
    if symbol:
        sql += " AND symbol = ?"
        params.append(symbol)
    sql += " ORDER BY signal_time ASC"
    with _lock, _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def _summarize(rows: list[Any]) -> dict[str, Any]:
    """Shared roll-up over a list of sqlite rows with status + pnl_pct."""
    wins = sum(1 for r in rows if r["status"] == "WIN")
    losses = sum(1 for r in rows if r["status"] == "LOSS")
    open_ct = sum(1 for r in rows if r["status"] == "OPEN")
    closed = wins + losses
    total_pnl = sum((r["pnl_pct"] or 0.0) for r in rows if r["status"] in ("WIN", "LOSS"))
    return {
        "total": len(rows),
        "closed": closed,
        "wins": wins,
        "losses": losses,
        "open": open_ct,
        "win_rate": (wins / closed * 100.0) if closed else 0.0,
        "total_pnl_pct": total_pnl,
        "avg_pnl_pct": (total_pnl / closed) if closed else 0.0,
    }


def list_trades(
    strategy_id: str | None = None,
    interval: str | None = None,
    symbol: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Most-recent-first list. Optional filters on strategy+interval+symbol
    so the Live tab only shows trades for the (coin, TF, strategy) the user
    is currently viewing -- never mixes BTC trades onto an ETH chart."""
    sql = "SELECT * FROM trades"
    where: list[str] = []
    params: list[Any] = []
    if strategy_id:
        where.append("strategy_id = ?")
        params.append(strategy_id)
    if interval:
        where.append("interval = ?")
        params.append(interval)
    if symbol:
        where.append("symbol = ?")
        params.append(symbol)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY signal_time DESC LIMIT ?"
    params.append(int(limit))
    with _lock, _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def stats(
    strategy_id: str | None = None,
    interval: str | None = None,
    symbol: str | None = None,
) -> dict[str, Any]:
    """Closed-trade summary scoped to one (strategy, interval, symbol).
    Matches the shape of trade_status.summarize() so the frontend can swap
    data sources transparently."""
    sql = "SELECT status, pnl_pct FROM trades"
    where: list[str] = []
    params: list[Any] = []
    if strategy_id:
        where.append("strategy_id = ?")
        params.append(strategy_id)
    if interval:
        where.append("interval = ?")
        params.append(interval)
    if symbol:
        where.append("symbol = ?")
        params.append(symbol)
    if where:
        sql += " WHERE " + " AND ".join(where)
    with _lock, _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return _summarize(rows)


def stats_in_window(
    start_ts: int,
    strategy_id: str | None = None,
    interval: str | None = None,
    symbol: str | None = None,
) -> dict[str, Any]:
    """Like stats() but only counts trades whose signal_time >= start_ts.
    Used by the leaderboard to rank rolling-window performance from real
    worker-fired trades (not in-memory backtest)."""
    sql = "SELECT status, pnl_pct FROM trades WHERE signal_time >= ?"
    params: list[Any] = [int(start_ts)]
    if strategy_id:
        sql += " AND strategy_id = ?"
        params.append(strategy_id)
    if interval:
        sql += " AND interval = ?"
        params.append(interval)
    if symbol:
        sql += " AND symbol = ?"
        params.append(symbol)
    with _lock, _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return _summarize(rows)


def all_strategy_intervals(symbol: str | None = None) -> list[tuple[str, str]]:
    """Distinct (strategy_id, interval) pairs that have at least one trade.
    Optionally restricted to a single symbol so the leaderboard can rank
    only the active coin without bleeding stats from other markets."""
    sql = "SELECT DISTINCT strategy_id, interval FROM trades"
    params: list[Any] = []
    if symbol:
        sql += " WHERE symbol = ?"
        params.append(symbol)
    with _lock, _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [(r["strategy_id"], r["interval"]) for r in rows]


def per_strategy_stats() -> list[dict[str, Any]]:
    """Roll-up grouped by (strategy_id, interval). Used by /api/trades/stats."""
    with _lock, _connect() as conn:
        rows = conn.execute(
            """
            SELECT strategy_id, interval,
                   COUNT(*) AS total,
                   SUM(CASE WHEN status = 'WIN'  THEN 1 ELSE 0 END) AS wins,
                   SUM(CASE WHEN status = 'LOSS' THEN 1 ELSE 0 END) AS losses,
                   SUM(CASE WHEN status = 'OPEN' THEN 1 ELSE 0 END) AS open_ct,
                   SUM(CASE WHEN status IN ('WIN','LOSS')
                            THEN pnl_pct ELSE 0 END) AS total_pnl_pct
              FROM trades
          GROUP BY strategy_id, interval
          ORDER BY strategy_id, interval
            """
        ).fetchall()
    out = []
    for r in rows:
        closed = (r["wins"] or 0) + (r["losses"] or 0)
        out.append({
            "strategy_id": r["strategy_id"],
            "interval": r["interval"],
            "total": r["total"],
            "wins": r["wins"] or 0,
            "losses": r["losses"] or 0,
            "open": r["open_ct"] or 0,
            "closed": closed,
            "win_rate": ((r["wins"] or 0) / closed * 100.0) if closed else 0.0,
            "total_pnl_pct": r["total_pnl_pct"] or 0.0,
            "avg_pnl_pct": ((r["total_pnl_pct"] or 0.0) / closed) if closed else 0.0,
        })
    return out


def per_pair_stats() -> list[dict[str, Any]]:
    """Roll-up grouped by (strategy_id, symbol). Drives the per-coin chip
    stats under each subscribed strategy in the AlertsTab — user can see
    at a glance which (strategy, coin) combos have edge before excluding."""
    with _lock, _connect() as conn:
        rows = conn.execute(
            """
            SELECT strategy_id, symbol,
                   COUNT(*) AS total,
                   SUM(CASE WHEN status = 'WIN'  THEN 1 ELSE 0 END) AS wins,
                   SUM(CASE WHEN status = 'LOSS' THEN 1 ELSE 0 END) AS losses,
                   SUM(CASE WHEN status = 'OPEN' THEN 1 ELSE 0 END) AS open_ct,
                   SUM(CASE WHEN status IN ('WIN','LOSS')
                            THEN pnl_pct ELSE 0 END) AS total_pnl_pct,
                   MAX(signal_time) AS last_signal_time
              FROM trades
          GROUP BY strategy_id, symbol
          ORDER BY strategy_id, symbol
            """
        ).fetchall()
    out = []
    for r in rows:
        closed = (r["wins"] or 0) + (r["losses"] or 0)
        out.append({
            "strategy_id": r["strategy_id"],
            "symbol": r["symbol"],
            "total": r["total"],
            "wins": r["wins"] or 0,
            "losses": r["losses"] or 0,
            "open": r["open_ct"] or 0,
            "closed": closed,
            "win_rate": ((r["wins"] or 0) / closed * 100.0) if closed else 0.0,
            "total_pnl_pct": r["total_pnl_pct"] or 0.0,
            "avg_pnl_pct": ((r["total_pnl_pct"] or 0.0) / closed) if closed else 0.0,
            "last_signal_time": r["last_signal_time"] or 0,
        })
    return out


def clear_all() -> int:
    """Wipe every row. Returns how many were removed."""
    with _lock, _connect() as conn:
        cur = conn.execute("DELETE FROM trades")
        conn.commit()
        return cur.rowcount
