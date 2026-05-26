"""Thin wrapper around Binance public market data.

Only the endpoints we need: historical klines (REST) and live kline stream (WS).
No API key required.
"""
from __future__ import annotations

import asyncio
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
    # market_rest + market_api_prefix swap between Spot's /api/v3 and
    # Futures' /fapi/v1 based on the BINANCE_MARKET env var. Response
    # shape is identical across both -- only the source diverges.
    url = f"{settings.market_rest}{settings.market_api_prefix}/klines"
    params = {"symbol": symbol.upper(), "interval": interval, "limit": limit}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return [_kline_to_candle(k) for k in resp.json()]


async def fetch_klines_paginated(symbol: str, interval: str, total_bars: int) -> list[Candle]:
    """Fetch up to `total_bars` historical klines by paging back in 1000-bar chunks.

    Binance caps each /klines call at 1000 rows; we walk backward using the
    `endTime` parameter until we have enough history. Returns chronological
    (oldest -> newest) without duplicates.
    """
    url = f"{settings.market_rest}{settings.market_api_prefix}/klines"
    all_candles: list[Candle] = []
    end_time_ms: int | None = None

    async with httpx.AsyncClient(timeout=15.0) as client:
        while len(all_candles) < total_bars:
            batch_size = min(1000, total_bars - len(all_candles))
            params = {
                "symbol": symbol.upper(),
                "interval": interval,
                "limit": batch_size,
            }
            if end_time_ms is not None:
                params["endTime"] = end_time_ms
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            raw = resp.json()
            if not raw:
                break  # exhausted available history
            batch = [_kline_to_candle(k) for k in raw]
            all_candles = batch + all_candles
            # Step back: 1ms before the oldest bar in this batch
            end_time_ms = batch[0].time * 1000 - 1
            await asyncio.sleep(0.05)  # gentle pacing

    return all_candles[-total_bars:] if all_candles else []


async def stream_klines(symbol: str, interval: str) -> AsyncIterator[Candle]:
    """Yields a Candle on every kline update from Binance.

    Note: Binance pushes the *current forming* bar repeatedly with `x: false`
    until it closes (`x: true`). We yield both states; downstream can decide
    whether to treat them as updates or appends by comparing the time field.
    """
    stream = f"{symbol.lower()}@kline_{interval}"
    url = f"{settings.market_ws}/{stream}"
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
