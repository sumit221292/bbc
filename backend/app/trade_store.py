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
                UNIQUE(strategy_id, interval, signal_time)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_trades_strat_interval "
            "ON trades(strategy_id, interval, signal_time DESC)"
        )
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


def close_trade(
    *,
    strategy_id: str,
    interval: str,
    signal_time: int,
    status: str,        # WIN or LOSS
    exit_price: float,
    exit_time: int,
    pnl_pct: float,
) -> bool:
    """Flip an OPEN row to its final WIN/LOSS state. No-op if already closed."""
    if status not in ("WIN", "LOSS"):
        return False
    with _lock, _connect() as conn:
        cur = conn.execute(
            """
            UPDATE trades
               SET status = ?, exit_price = ?, exit_time = ?, pnl_pct = ?
             WHERE strategy_id = ? AND interval = ? AND signal_time = ?
               AND status = 'OPEN'
            """,
            (status, exit_price, exit_time, pnl_pct,
             strategy_id, interval, signal_time),
        )
        conn.commit()
        return cur.rowcount > 0


def open_trades(strategy_id: str, interval: str) -> list[dict[str, Any]]:
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM trades WHERE strategy_id = ? AND interval = ? "
            "AND status = 'OPEN' ORDER BY signal_time ASC",
            (strategy_id, interval),
        ).fetchall()
    return [dict(r) for r in rows]


def list_trades(
    strategy_id: str | None = None,
    interval: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Most-recent-first list. Optional filters on strategy+interval so the
    Live tab shows only the trades that match the current view."""
    sql = "SELECT * FROM trades"
    where: list[str] = []
    params: list[Any] = []
    if strategy_id:
        where.append("strategy_id = ?")
        params.append(strategy_id)
    if interval:
        where.append("interval = ?")
        params.append(interval)
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
) -> dict[str, Any]:
    """Closed-trade summary scoped to one (strategy, interval) when both are
    set, otherwise broader. Matches the shape of trade_status.summarize() so
    the frontend can swap data sources transparently."""
    sql = (
        "SELECT status, pnl_pct FROM trades"
    )
    where: list[str] = []
    params: list[Any] = []
    if strategy_id:
        where.append("strategy_id = ?")
        params.append(strategy_id)
    if interval:
        where.append("interval = ?")
        params.append(interval)
    if where:
        sql += " WHERE " + " AND ".join(where)
    with _lock, _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
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


def clear_all() -> int:
    """Wipe every row. Returns how many were removed."""
    with _lock, _connect() as conn:
        cur = conn.execute("DELETE FROM trades")
        conn.commit()
        return cur.rowcount
