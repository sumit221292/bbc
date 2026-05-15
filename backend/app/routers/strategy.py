import asyncio
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from .. import trade_store
from ..backtest import simulate
from ..binance import fetch_klines
from ..multi_tf import MTFContext
from ..schemas import Signal, StrategyMeta, StrategyResult, StrategySummary
from ..smc_mtf import SMCMTFContext
from ..strategies import (
    get_strategy, is_mtf, is_smc_mtf, list_mtf_metas, list_strategies,
    run_mtf, run_smc_mtf,
)
from ..trade_status import annotate, summarize

router = APIRouter(prefix="/api/strategy", tags=["strategy"])


# Global minimum risk:reward — strategies that emit signals worse than this
# get them filtered out before annotation/simulation. The user requested
# "minimum 1:2 RR or no trade" across every strategy and timeframe.
MIN_RR = 2.0


def _filter_min_rr(signals: list[Signal], min_rr: float = MIN_RR) -> list[Signal]:
    """Drop signals whose reward/risk ratio is below `min_rr`. Signals that
    are missing entry/stop/target are kept (e.g. HOLD markers)."""
    out: list[Signal] = []
    for s in signals:
        if s.entry is None or s.stop_loss is None or s.target is None:
            out.append(s)
            continue
        risk = abs(s.entry - s.stop_loss)
        if risk <= 0:
            continue  # malformed signal, drop
        reward = abs(s.target - s.entry)
        if (reward / risk) >= min_rr:
            out.append(s)
    return out


@router.get("/list", response_model=list[StrategyMeta])
def get_strategy_list():
    # MTF strategies first so they show up at the top of the UI selector.
    return list_mtf_metas() + [s.meta() for s in list_strategies()]


def _build_result(strategy_id: str, symbol: str, interval: str,
                  candles, signals: list[Signal],
                  partial_at_r: float | None = None) -> StrategyResult:
    """Shared post-processing: annotate trade status, pick latest, build summary.

    Signals with RR below MIN_RR (1:2) are dropped first.

    Summary uses the proper trade simulator (one trade at a time, 2% risk per
    trade on a $1000 starting capital, compounded, with 0.2% round-trip fees).

    If `partial_at_r` is set, the simulator scales out 50% at that R-multiple
    and moves the stop to breakeven. Used by SMC MTF for higher expectancy.
    """
    signals = _filter_min_rr(signals)
    signals = annotate(signals, candles)
    last_candle = candles[-1]

    open_trades = [s for s in signals if s.status == "OPEN"]
    if open_trades:
        latest = open_trades[-1]
    else:
        latest = Signal(
            time=last_candle.time, type="HOLD", price=last_candle.close,
            reason="Koi active trade nahi -- next signal ka wait karo",
        )

    counts = summarize(signals)
    sim = simulate(candles, signals, partial_at_r=partial_at_r)
    closed = counts["wins"] + counts["losses"]
    summary = StrategySummary(
        total=counts["total"],
        closed=counts["closed"],
        wins=counts["wins"],
        losses=counts["losses"],
        open=counts["open"],
        win_rate=counts["win_rate"],
        total_pnl_pct=sim["total_pnl_pct"],
        avg_pnl_pct=(sim["total_pnl_pct"] / closed) if closed else 0.0,
    )

    return StrategyResult(
        strategy=strategy_id, symbol=symbol.upper(), interval=interval,
        signals=signals, latest=latest, summary=summary,
    )


class StrategySnapshot(BaseModel):
    id: str
    name: str
    category: str
    signal: str             # 'BUY' | 'SELL' | 'HOLD'
    status: Optional[str]   # 'OPEN' | 'WIN' | 'LOSS' | None
    entry: Optional[float]
    stop_loss: Optional[float]
    target: Optional[float]
    pnl_pct: Optional[float]   # live mark-to-market for OPEN, realized for closed
    win_rate: float
    total_pnl_pct: float
    total_trades: int
    last_signal_time: Optional[int]


class SnapshotResponse(BaseModel):
    symbol: str
    interval: str
    generated_at: int
    strategies: list[StrategySnapshot]


# Map strategy id -> category (matches the frontend dropdown groups).
_CATEGORIES: dict[str, str] = {
    "mtf_chop_aware": "Recommended (Multi-TF)",
    "mtf_strict": "Recommended (Multi-TF)",
    "mtf_2screen": "Recommended (Multi-TF)",
    "mtf_chop_only": "Recommended (Multi-TF)",
    "smc_mtf": "Smart Money",
    "smc_trend_liq": "Smart Money",
    "champion": "Champion",
    "best": "Selective",
    "smc_momentum": "Smart Money",
    "trend_following": "Trend",
    "day_trading": "Trend",
    "adx_trend": "Trend",
    "macd": "Trend",
    "supertrend": "Trend",
    "ichimoku": "Trend",
    "bollinger": "Mean Reversion",
    "stochastic": "Mean Reversion",
    "swing": "Mean Reversion",
    "scalping": "Mean Reversion",
    "breakout": "Breakout",
    "donchian": "Breakout",
}


def _db_interval_for(sid: str, user_interval: str) -> str:
    """Which DB partition holds this strategy's trades.

    Must match how the alert worker keys rows: MTF always runs on 1h,
    SMC MTF on 5m, every other strategy on whichever interval the user
    subscribed (we use the snapshot's user_interval as the closest proxy)."""
    if is_smc_mtf(sid):
        return "5m"
    if is_mtf(sid):
        return "1h"
    return user_interval


def _build_snapshot(
    sid: str, name: str, signals: list[Signal], candles, user_interval: str,
) -> StrategySnapshot:
    """Live signal + DB stats. The signal half (BUY/SELL/HOLD, entry, SL,
    target, mark-to-market PnL) must come from fresh candles, because that
    is what the user trades against right now. Win rate / total trades /
    cumulative PnL come from trade_store so the numbers reflect what the
    worker has actually fired -- never from in-memory backtest.
    """
    signals = _filter_min_rr(signals)
    last_close = candles[-1].close
    open_trades = [s for s in signals if s.status == "OPEN"]
    if open_trades:
        latest = open_trades[-1]
        signal_type = latest.type
        status = latest.status
        entry, stop, target = latest.entry, latest.stop_loss, latest.target
        if entry:
            if signal_type == "BUY":
                pnl_live = (last_close - entry) / entry * 100.0
            else:
                pnl_live = (entry - last_close) / entry * 100.0
        else:
            pnl_live = None
        last_time = latest.time
    else:
        signal_type = "HOLD"
        status = None
        entry = stop = target = pnl_live = None
        last_time = signals[-1].time if signals else None

    db_interval = _db_interval_for(sid, user_interval)
    db = trade_store.stats(strategy_id=sid, interval=db_interval)
    return StrategySnapshot(
        id=sid, name=name,
        category=_CATEGORIES.get(sid, "Other"),
        signal=signal_type, status=status,
        entry=entry, stop_loss=stop, target=target,
        pnl_pct=pnl_live,
        win_rate=db["win_rate"],            # live-trade hit rate from DB
        total_pnl_pct=db["total_pnl_pct"],  # live-trade cumulative PnL
        total_trades=db["total"],           # live trades count
        last_signal_time=last_time,
    )


@router.get("/snapshot", response_model=SnapshotResponse)
async def get_snapshot(
    symbol: str = Query("BTCUSDT"),
    interval: str = Query("1h", description="Timeframe for single-TF strategies"),
):
    """Returns the current state of every registered strategy in one call.

    Single-TF strategies are computed on the requested `interval` (default 1h).
    MTF strategies always use their native 1h/4h/1d (and 5m for SMC MTF).

    Passing interval matches the snapshot to whatever the user is currently
    viewing on the chart, so notifications align with what they see.
    """
    try:
        # 1h / 4h / 1d are always needed for MTF context.
        c1h, c4h, c1d = await asyncio.gather(
            fetch_klines(symbol, "1h", 1000),
            fetch_klines(symbol, "4h", 1000),
            fetch_klines(symbol, "1d", 1000),
        )
        # If the user picked a non-1h interval, fetch that too for single-TF.
        if interval == "1h":
            c_int = c1h
        else:
            c_int = await fetch_klines(symbol, interval, 500)
    except Exception as e:
        raise HTTPException(502, f"Binance error: {e}")

    ctx = MTFContext(candles_1h=c1h, candles_4h=c4h, candles_1d=c1d)

    # SMC MTF needs 5m/15m candles in addition. Fetch lazily so we don't
    # waste a request when there's no SMC strategy registered.
    smc_ctx: SMCMTFContext | None = None
    if any(is_smc_mtf(meta.id) for meta in list_mtf_metas()):
        try:
            c5, c15 = await asyncio.gather(
                fetch_klines(symbol, "5m", 1000),
                fetch_klines(symbol, "15m", 500),
            )
            smc_ctx = SMCMTFContext(candles_5m=c5, candles_15m=c15, candles_1h=c1h)
        except Exception:
            smc_ctx = None

    rows: list[StrategySnapshot] = []

    # MTF strategies first. smc_mtf has its own context + entry timeframe (5m).
    for meta in list_mtf_metas():
        if is_smc_mtf(meta.id):
            if smc_ctx is None:
                continue  # data fetch failed; skip rather than 500
            signals = annotate(run_smc_mtf(meta.id, smc_ctx, start_idx=60), smc_ctx.candles_5m)
            rows.append(_build_snapshot(meta.id, meta.name, signals, smc_ctx.candles_5m, interval))
        else:
            signals = annotate(run_mtf(meta.id, ctx, start_idx=50), c1h)
            rows.append(_build_snapshot(meta.id, meta.name, signals, c1h, interval))

    # Single-TF strategies on the requested interval
    for cls in list_strategies():
        signals = annotate(cls().evaluate(c_int), c_int)
        rows.append(_build_snapshot(cls.id, cls.name, signals, c_int, interval))

    return SnapshotResponse(
        symbol=symbol.upper(), interval=interval,
        generated_at=c_int[-1].time, strategies=rows,
    )


class LeaderboardEntry(BaseModel):
    strategy_id: str
    strategy_name: str
    timeframe: str
    trades: int
    wins: int
    losses: int
    open: int
    win_rate: float
    total_pnl_pct: float


class WindowLeaderboard(BaseModel):
    window_hours: int
    top: list[LeaderboardEntry]
    any_traded: bool


class LeaderboardResponse(BaseModel):
    symbol: str
    generated_at: int
    leaderboards: list[WindowLeaderboard]


_LB_WINDOWS_HOURS: list[int] = [1, 2, 4, 6, 12, 24]


@router.get("/leaderboard", response_model=LeaderboardResponse)
async def get_leaderboard(symbol: str = Query("BTCUSDT")):
    """Top (strategy, timeframe) combos by realized PnL, ranked from real
    worker-fired trades only. Each rolling window filters DB rows by
    signal_time. No Binance fetch needed -- the leaderboard is purely a
    view over trade_store, so it stays accurate even when the market API
    is rate-limited."""
    name_for: dict[str, str] = {cls.id: cls.name for cls in list_strategies()}
    for meta in list_mtf_metas():
        name_for[meta.id] = meta.name

    combos = trade_store.all_strategy_intervals()
    now_ts = int(datetime.now(timezone.utc).timestamp())
    leaderboards: list[WindowLeaderboard] = []

    for hours in _LB_WINDOWS_HOURS:
        cutoff = now_ts - hours * 3600
        scored: list[LeaderboardEntry] = []
        for sid, tf in combos:
            s = trade_store.stats_in_window(cutoff, strategy_id=sid, interval=tf)
            if s["total"] == 0:
                continue
            scored.append(LeaderboardEntry(
                strategy_id=sid,
                strategy_name=name_for.get(sid, sid),
                timeframe=tf,
                trades=s["total"],
                wins=s["wins"],
                losses=s["losses"],
                open=s["open"],
                win_rate=s["win_rate"],
                total_pnl_pct=s["total_pnl_pct"],
            ))
        scored.sort(key=lambda e: e.total_pnl_pct, reverse=True)
        leaderboards.append(WindowLeaderboard(
            window_hours=hours, top=scored[:3], any_traded=len(scored) > 0,
        ))

    return LeaderboardResponse(
        symbol=symbol.upper(), generated_at=now_ts, leaderboards=leaderboards,
    )


@router.get("/run", response_model=StrategyResult)
async def run_strategy(
    id: str = Query(..., description="Strategy id, e.g. 'best' or 'mtf_chop_aware'"),
    symbol: str = Query("BTCUSDT"),
    interval: str = Query("1m"),
    limit: int = Query(500, ge=50, le=1000),
):
    # ---- SMC Multi-TF: 5m execution + 15m structure + 1h trend ----
    if is_smc_mtf(id):
        try:
            c5, c15, c1h = await asyncio.gather(
                fetch_klines(symbol, "5m", 1000),
                fetch_klines(symbol, "15m", 500),
                fetch_klines(symbol, "1h", 300),
            )
        except Exception as e:
            raise HTTPException(502, f"Binance error: {e}")
        smc_ctx = SMCMTFContext(candles_5m=c5, candles_15m=c15, candles_1h=c1h)
        signals = run_smc_mtf(id, smc_ctx, start_idx=60)
        # Multi-target: scale out 50% at 1R, move stop to breakeven for the rest.
        return _build_result(id, symbol, "5m", c5, signals, partial_at_r=1.0)

    # ---- Multi-TF strategies: 1h / 4h / 1d, ignore the `interval` param ----
    if is_mtf(id):
        try:
            c1h, c4h, c1d = await asyncio.gather(
                fetch_klines(symbol, "1h", 1000),
                fetch_klines(symbol, "4h", 1000),
                fetch_klines(symbol, "1d", 1000),
            )
        except Exception as e:
            raise HTTPException(502, f"Binance error: {e}")
        ctx = MTFContext(candles_1h=c1h, candles_4h=c4h, candles_1d=c1d)
        signals = run_mtf(id, ctx, start_idx=50)
        # MTF always reports its results on the 1h timeframe (the entry TF).
        return _build_result(id, symbol, "1h", c1h, signals)

    # ---- Standard single-TF strategies ----
    try:
        strat = get_strategy(id)
    except KeyError:
        raise HTTPException(404, f"Unknown strategy '{id}'")
    candles = await fetch_klines(symbol, interval, limit)
    signals = strat.evaluate(candles)
    return _build_result(id, symbol, interval, candles, signals)
