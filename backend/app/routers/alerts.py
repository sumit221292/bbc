"""Alerts API — frontend syncs Telegram setup + subscriptions to backend."""
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..alerts import (
    AlertConfig, AutoTradeConfig, CONFIRM_PHRASE, MAX_RISK_PCT,
    OpenPosition, Subscription, load_config, save_config, send_telegram,
)
from ..binance_trade import cancel_all_open_orders, test_credentials

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


class ConfigUpdate(BaseModel):
    token: str = ""
    chat_id: str = ""                     # legacy single chat
    chat_ids: list[str] = []              # new: multiple recipients
    enabled: bool = True
    symbol: str = "BTCUSDT"               # auto-trade target (single)
    symbols: list[str] = []               # multi-coin watchlist for signals
    subscriptions: list[Subscription] = []


class TestRequest(BaseModel):
    token: str
    chat_id: str = ""                     # legacy
    chat_ids: list[str] = []              # new


class AutoTradeView(BaseModel):
    """Redacted auto-trade settings for the frontend (no secrets)."""
    enabled: bool
    has_api_key: bool
    has_api_secret: bool
    has_confirmation: bool       # whether CONFIRM_PHRASE was saved
    capital_usd: float
    risk_pct: float
    max_position_usd: float
    max_trades_per_day: int
    max_daily_loss_pct: float
    allowed_strategies: list[str]
    current_position: OpenPosition | None
    trades_today: int
    loss_today_pct: float
    last_trade_error: str
    halted_reason: str


class ConfigResponse(BaseModel):
    """What we expose to the frontend. Token is partly redacted for safety."""
    has_token: bool
    chat_id: str                      # legacy single
    chat_ids: list[str]               # new multi
    enabled: bool
    symbol: str                       # auto-trade target
    symbols: list[str]                # multi-coin watchlist
    subscriptions: list[Subscription]
    last_seen: dict[str, int]
    last_poll: int
    last_error: str
    auto_trade: AutoTradeView


def _auto_view(at: AutoTradeConfig) -> AutoTradeView:
    return AutoTradeView(
        enabled=at.enabled,
        has_api_key=bool(at.api_key),
        has_api_secret=bool(at.api_secret),
        has_confirmation=at.confirmation == CONFIRM_PHRASE,
        capital_usd=at.capital_usd,
        risk_pct=at.risk_pct,
        max_position_usd=at.max_position_usd,
        max_trades_per_day=at.max_trades_per_day,
        max_daily_loss_pct=at.max_daily_loss_pct,
        allowed_strategies=at.allowed_strategies,
        current_position=at.current_position,
        trades_today=at.trades_today,
        loss_today_pct=at.loss_today_pct,
        last_trade_error=at.last_trade_error,
        halted_reason=at.halted_reason,
    )


def _to_response(cfg: AlertConfig) -> ConfigResponse:
    return ConfigResponse(
        has_token=bool(cfg.token),
        chat_id=cfg.chat_id,
        chat_ids=cfg.chat_ids,
        enabled=cfg.enabled,
        symbol=cfg.symbol,
        symbols=cfg.symbols or [cfg.symbol],
        subscriptions=cfg.subscriptions,
        last_seen=cfg.last_seen,
        last_poll=cfg.last_poll,
        last_error=cfg.last_error,
        auto_trade=_auto_view(cfg.auto_trade),
    )


@router.get("/config", response_model=ConfigResponse)
async def get_alerts_config():
    cfg = await load_config()
    return _to_response(cfg)


@router.post("/config", response_model=ConfigResponse)
async def update_alerts_config(payload: ConfigUpdate):
    cfg = await load_config()
    # Only overwrite token if a non-empty one was sent (so frontend can
    # send other fields without re-sending the secret every time).
    if payload.token:
        cfg.token = payload.token
    cfg.chat_id = payload.chat_id
    # Clean up the multi-chat list: strip whitespace, drop blanks/dupes.
    cleaned = []
    seen = set()
    for cid in payload.chat_ids:
        c = (cid or "").strip()
        if c and c not in seen:
            seen.add(c)
            cleaned.append(c)
    cfg.chat_ids = cleaned
    cfg.symbol = (payload.symbol or "BTCUSDT").upper()
    # Clean + upper-case + dedupe the multi-coin watchlist. Always include
    # the auto-trade symbol so the worker fires there even if the user
    # forgot to tick it.
    sym_list: list[str] = []
    sym_seen: set[str] = set()
    for s in [*payload.symbols, cfg.symbol]:
        u = (s or "").strip().upper()
        if u and u not in sym_seen:
            sym_seen.add(u)
            sym_list.append(u)
    cfg.symbols = sym_list or [cfg.symbol]

    has_chat = bool(payload.chat_id or cleaned)
    has_full = bool(cfg.token and has_chat and payload.subscriptions)
    cfg.enabled = payload.enabled if not has_full else True

    # Normalise each subscription's exclusion list: upper-case to match
    # cfg.symbols, drop blanks + dupes. Done in-place on the payload so
    # the cross-product below sees the cleaned values.
    for s in payload.subscriptions:
        seen_ex: set[str] = set()
        norm: list[str] = []
        for sym in s.excluded:
            u = (sym or "").strip().upper()
            if u and u not in seen_ex:
                seen_ex.add(u)
                norm.append(u)
        s.excluded = norm

    # last_seen keys are now "symbol::strategy_id" composites. Sync to the
    # cross product of (active symbols x active subscriptions), MINUS any
    # (symbol, strategy) pair the user has excluded. Dropping excluded
    # combos from last_seen means re-enabling later stamps a fresh "now"
    # instead of back-firing every signal accumulated while it was off.
    now = int(time.time())
    new_combos = {
        f"{sym}::{s.strategy_id}"
        for sym in cfg.symbols
        for s in payload.subscriptions
        if sym not in s.excluded
    }
    old_keys = set(cfg.last_seen)
    for k in new_combos - old_keys:
        cfg.last_seen[k] = now
    for k in list(cfg.last_seen):
        if k not in new_combos:
            cfg.last_seen.pop(k, None)
    for k in list(cfg.pending_close):
        if k not in new_combos:
            cfg.pending_close.pop(k, None)

    cfg.subscriptions = payload.subscriptions
    cfg.last_error = ""
    await save_config(cfg)
    return _to_response(cfg)


class AutoTradeUpdate(BaseModel):
    enabled: bool = False
    api_key: str = ""             # blank = keep existing
    api_secret: str = ""          # blank = keep existing
    capital_usd: float = 100.0
    risk_pct: float = 0.01
    max_position_usd: float = 500.0
    max_trades_per_day: int = 5
    max_daily_loss_pct: float = 0.05
    confirmation: str = ""        # user must type CONFIRM_PHRASE to enable
    allowed_strategies: list[str] = []


@router.post("/auto", response_model=AutoTradeView)
async def update_auto_trade(payload: AutoTradeUpdate):
    """Update auto-trade settings. Many guardrails enforced here."""
    cfg = await load_config()
    at = cfg.auto_trade

    # Hard-cap risk regardless of what the user sends.
    risk = min(max(payload.risk_pct, 0.001), MAX_RISK_PCT)

    # Only overwrite secrets if non-empty so the frontend doesn't need to
    # round-trip them.
    if payload.api_key:
        at.api_key = payload.api_key
    if payload.api_secret:
        at.api_secret = payload.api_secret
    at.capital_usd = max(10.0, payload.capital_usd)
    at.risk_pct = risk
    at.max_position_usd = max(10.0, payload.max_position_usd)
    at.max_trades_per_day = max(1, min(payload.max_trades_per_day, 50))
    at.max_daily_loss_pct = max(0.01, min(payload.max_daily_loss_pct, 0.20))
    at.confirmation = payload.confirmation
    at.allowed_strategies = payload.allowed_strategies

    # Refuse to enable unless ALL safety conditions are met.
    can_enable = (
        at.api_key
        and at.api_secret
        and at.confirmation == CONFIRM_PHRASE
        and at.allowed_strategies
    )
    if payload.enabled and not can_enable:
        raise HTTPException(
            400,
            "Cannot enable auto-trade: need api_key + api_secret + "
            f"confirmation='{CONFIRM_PHRASE}' + at least 1 allowed_strategy",
        )
    at.enabled = payload.enabled and can_enable

    # Clearing the halt is a side-effect of toggling enabled on.
    if at.enabled:
        at.halted_reason = ""

    cfg.auto_trade = at
    await save_config(cfg)
    return _auto_view(cfg.auto_trade)


class CredentialsTestRequest(BaseModel):
    api_key: str
    api_secret: str


@router.post("/auto/test")
async def test_auto_credentials(payload: CredentialsTestRequest):
    """Verify the Binance API key without placing any orders."""
    ok, msg = await test_credentials(payload.api_key, payload.api_secret)
    return {"ok": ok, "message": msg}


@router.post("/auto/kill")
async def kill_auto_trade():
    """Emergency stop: disable auto-trade and cancel all open orders on the symbol.
    Existing positions are NOT closed — you must close those manually."""
    cfg = await load_config()
    at = cfg.auto_trade
    at.enabled = False
    at.halted_reason = "manual kill switch fired"

    cancelled = None
    if at.api_key and at.api_secret:
        try:
            cancelled = await cancel_all_open_orders(at.api_key, at.api_secret, cfg.symbol)
        except Exception as e:
            cancelled = {"error": str(e)}

    cfg.auto_trade = at
    await save_config(cfg)
    return {
        "ok": True,
        "auto_trade": _auto_view(at),
        "cancelled_orders": cancelled,
        "note": (
            "Open orders cancelled. Any FILLED positions remain — close them "
            "manually on Binance if needed."
        ),
    }


@router.post("/test")
async def send_test(payload: TestRequest):
    """Fire a test message to every chat_id provided (legacy + new list)."""
    from ..alerts import broadcast_telegram
    targets: list[str] = []
    seen = set()
    for cid in [payload.chat_id, *payload.chat_ids]:
        c = (cid or "").strip()
        if c and c not in seen:
            seen.add(c)
            targets.append(c)
    if not targets:
        raise HTTPException(400, "no chat_id provided")
    any_ok, summary = await broadcast_telegram(
        payload.token, targets,
        "✅ *Backend worker test*\n\n"
        "Notifications setup OK! Yeh message backend se aaya hai. "
        "Ab browser band ho ya khulla, alerts aate rahenge.",
    )
    if not any_ok:
        raise HTTPException(400, f"Telegram error: 0/{len(targets)} delivered")
    return {"ok": True, "summary": summary, "targets": len(targets)}
