from fastapi import APIRouter, HTTPException, Query

from ..binance import fetch_klines
from ..indicators import ema, rsi
from ..schemas import Candle

router = APIRouter(prefix="/api/market", tags=["market"])


@router.get("/klines", response_model=list[Candle])
async def get_klines(
    symbol: str = Query("BTCUSDT"),
    interval: str = Query("1m"),
    limit: int = Query(500, ge=10, le=1000),
):
    try:
        return await fetch_klines(symbol, interval, limit)
    except Exception as e:
        raise HTTPException(502, f"Binance error: {e}")


@router.get("/indicators")
async def get_indicators(
    symbol: str = Query("BTCUSDT"),
    interval: str = Query("1m"),
    limit: int = Query(500, ge=50, le=1000),
):
    """Returns EMA(20/50/200) and RSI(14) aligned with the same kline series."""
    candles = await fetch_klines(symbol, interval, limit)
    closes = [c.close for c in candles]
    times = [c.time for c in candles]
    return {
        "time": times,
        "ema20": ema(closes, 20),
        "ema50": ema(closes, 50),
        "ema200": ema(closes, 200),
        "rsi14": rsi(closes, 14),
    }
