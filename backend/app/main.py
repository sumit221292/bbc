"""FastAPI entrypoint.

Run with:
    uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .alerts import alert_loop
from .binance import stream_klines
from .config import settings
from .routers import alerts as alerts_router
from .routers import auth as auth_router
from .routers import market, outlook, strategy
from .routers import trades as trades_router
from . import trade_store

log = logging.getLogger("btc")

app = FastAPI(title="BTC/USDT Trading Analysis API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    # In production the frontend is served same-origin from this FastAPI
    # process (static mount below), so CORS effectively never fires for
    # real users. For local dev the Vite proxy keeps requests same-origin
    # too. The cors_origins list only matters if someone hosts the
    # frontend on a separate domain, in which case allow_credentials
    # must be True for the auth cookie to round-trip -- and the origin
    # list MUST be specific (browsers reject "*" with credentials).
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(market.router)
app.include_router(strategy.router)
app.include_router(outlook.router)
app.include_router(alerts_router.router)
app.include_router(trades_router.router)


@app.on_event("startup")
async def _start_alert_worker():
    """Always-on Telegram notification worker.

    Also dumps the trade-history row count + DB path on boot so any
    surprise reset (volume not mounted, file deleted, etc.) is visible
    in Railway logs the moment it happens, instead of being noticed
    days later when the user opens the dashboard."""
    trade_store.init_db()
    try:
        existing = trade_store.list_trades(limit=1)
        stats = trade_store.stats()
        log.info(
            "[BOOT] trade_store ready at %s -- %d total rows (%d closed, %d open). "
            "Most-recent signal_time=%s",
            trade_store.DB_PATH, stats["total"], stats["closed"], stats["open"],
            existing[0]["signal_time"] if existing else "none",
        )
    except Exception:
        log.exception("[BOOT] trade_store sanity dump failed")
    app.state.alert_task = asyncio.create_task(alert_loop())


@app.on_event("shutdown")
async def _stop_alert_worker():
    task = getattr(app.state, "alert_task", None)
    if task:
        task.cancel()


@app.get("/healthz")
def healthz():
    """Health check for Railway / load balancers. Cheap, no Binance call."""
    return {"status": "ok"}


@app.websocket("/ws/klines")
async def ws_klines(websocket: WebSocket):
    """Live kline stream proxied from Binance.

    Query params:
        symbol   default BTCUSDT
        interval default 1m
    """
    await websocket.accept()
    symbol = websocket.query_params.get("symbol", settings.default_symbol)
    interval = websocket.query_params.get("interval", settings.default_interval)

    send_lock = asyncio.Lock()

    async def pump():
        try:
            async for candle in stream_klines(symbol, interval):
                async with send_lock:
                    await websocket.send_json(candle.model_dump())
        except Exception as e:  # network blip, Binance reset, etc.
            log.warning("stream ended: %s", e)

    pump_task = asyncio.create_task(pump())
    try:
        # Drain client messages so the socket closes cleanly when the user navigates away.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        pump_task.cancel()


# In production we serve the built React app from this same FastAPI process.
# The Dockerfile copies frontend/dist -> /app/frontend_dist. If the directory
# exists, mount it at the root path. API and WebSocket routes registered above
# are checked before this catch-all mount.
_frontend_dir = Path(__file__).resolve().parent.parent / "frontend_dist"
if _frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dir), html=True), name="frontend")
