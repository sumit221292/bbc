"""Alerts API — frontend syncs Telegram setup + subscriptions to backend."""
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..alerts import (
    AlertConfig, Subscription, load_config, save_config, send_telegram,
)

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


class ConfigUpdate(BaseModel):
    token: str = ""
    chat_id: str = ""
    enabled: bool = True
    symbol: str = "BTCUSDT"
    subscriptions: list[Subscription] = []


class TestRequest(BaseModel):
    token: str
    chat_id: str


class ConfigResponse(BaseModel):
    """What we expose to the frontend. Token is partly redacted for safety."""
    has_token: bool
    chat_id: str
    enabled: bool
    symbol: str
    subscriptions: list[Subscription]
    last_seen: dict[str, int]
    last_poll: int
    last_error: str


def _to_response(cfg: AlertConfig) -> ConfigResponse:
    return ConfigResponse(
        has_token=bool(cfg.token),
        chat_id=cfg.chat_id,
        enabled=cfg.enabled,
        symbol=cfg.symbol,
        subscriptions=cfg.subscriptions,
        last_seen=cfg.last_seen,
        last_poll=cfg.last_poll,
        last_error=cfg.last_error,
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
    cfg.symbol = payload.symbol or "BTCUSDT"
    # Auto-enable when the config is fully populated. Without this, on a
    # fresh Railway deploy the alerts_config.json is reset (enabled=false)
    # and the frontend's first GET propagates that 'false' back into the
    # form -- the user clicks Save thinking they're enabling, but they're
    # silently saving a paused worker. Now: if the user has token + chat_id
    # + at least one subscription, we force enabled=True. To pause, they
    # send subs=[] or call the (future) /pause endpoint.
    has_full = bool(cfg.token and payload.chat_id and payload.subscriptions)
    cfg.enabled = payload.enabled if not has_full else True

    now = int(time.time())
    new_ids = {s.strategy_id for s in payload.subscriptions}
    old_ids = {s.strategy_id for s in cfg.subscriptions}
    # New subscriptions: mark "now" as last_seen so we don't backfill.
    for sid in new_ids - old_ids:
        cfg.last_seen[sid] = now
    # Removed subscriptions: drop their last_seen.
    for sid in list(cfg.last_seen):
        if sid not in new_ids:
            cfg.last_seen.pop(sid, None)

    cfg.subscriptions = payload.subscriptions
    cfg.last_error = ""
    await save_config(cfg)
    return _to_response(cfg)


@router.post("/test")
async def send_test(payload: TestRequest):
    ok, err = await send_telegram(
        payload.token, payload.chat_id,
        "✅ *Backend worker test*\n\n"
        "Notifications setup OK! Yeh message backend se aaya hai. "
        "Ab browser band ho ya khulla, alerts aate rahenge.",
    )
    if not ok:
        raise HTTPException(400, f"Telegram error: {err}")
    return {"ok": True}
