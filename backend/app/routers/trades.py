"""Trade history API — only persists alert-worker signals (no backtest noise)."""
from fastapi import APIRouter, Query

from .. import trade_store

router = APIRouter(prefix="/api/trades", tags=["trades"])


@router.get("")
async def list_trades(
    strategy: str | None = Query(default=None),
    interval: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=2000),
):
    """Most-recent-first list. When strategy + interval + symbol are all
    given the response is exactly the trades a user would see for that
    view -- never mixes coins, timeframes, or strategies."""
    sym = symbol.upper() if symbol else None
    rows = trade_store.list_trades(
        strategy_id=strategy, interval=interval, symbol=sym, limit=limit,
    )
    summary = trade_store.stats(strategy_id=strategy, interval=interval, symbol=sym)
    return {"trades": rows, "summary": summary}


@router.get("/stats")
async def all_stats():
    """Per-(strategy, interval) summary. Drives any leaderboard view."""
    return {"groups": trade_store.per_strategy_stats()}


# NOTE: a DELETE /api/trades endpoint used to live here but was removed
# at the user's request -- the worker spends days building up trade
# history and a single accidental curl could wipe everything. The
# clear_all() function still exists in trade_store for tests + manual
# database surgery, but it is no longer reachable over HTTP. If a true
# reset is ever needed, edit the volume directly on Railway.
