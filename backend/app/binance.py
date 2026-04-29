"""Thin wrapper around Binance public market data.

Only the endpoints we need: historical klines (REST) and live kline stream (WS).
No API key required.
"""
from __future__ import annotations

import json
from typing import AsyncIterator

import httpx
import websockets

from .config import settings
from .schemas import Candle


def _kline_to_candle(k: list) -> Candle:
    # Binance kline payload layout:
    # [openTime, open, high, low, close, volume, closeTime, ...]
    return Candle(
        time=int(k[0]) // 1000,
        open=float(k[1]),
        high=float(k[2]),
        low=float(k[3]),
        close=float(k[4]),
        volume=float(k[5]),
    )


async def fetch_klines(symbol: str, interval: str, limit: int = 500) -> list[Candle]:
    url = f"{settings.binance_rest}/api/v3/klines"
    params = {"symbol": symbol.upper(), "interval": interval, "limit": limit}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return [_kline_to_candle(k) for k in resp.json()]


async def stream_klines(symbol: str, interval: str) -> AsyncIterator[Candle]:
    """Yields a Candle on every kline update from Binance.

    Note: Binance pushes the *current forming* bar repeatedly with `x: false`
    until it closes (`x: true`). We yield both states; downstream can decide
    whether to treat them as updates or appends by comparing the time field.
    """
    stream = f"{symbol.lower()}@kline_{interval}"
    url = f"{settings.binance_ws}/{stream}"
    async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
        async for raw in ws:
            msg = json.loads(raw)
            k = msg.get("k")
            if not k:
                continue
            yield Candle(
                time=int(k["t"]) // 1000,
                open=float(k["o"]),
                high=float(k["h"]),
                low=float(k["l"]),
                close=float(k["c"]),
                volume=float(k["v"]),
            )
