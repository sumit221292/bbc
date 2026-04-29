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

from .binance import stream_klines
from .config import settings
from .routers import market, outlook, strategy

log = logging.getLogger("btc")

app = FastAPI(title="BTC/USDT Trading Analysis API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    # No cookies/auth in this app — keep this False so wildcard origins work.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(market.router)
app.include_router(strategy.router)
app.include_router(outlook.router)


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
