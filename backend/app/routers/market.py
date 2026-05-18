import time
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query

from ..binance import fetch_klines
from ..config import settings
from ..indicators import ema, rsi
from ..schemas import Candle

router = APIRouter(prefix="/api/market", tags=["market"])

# In-memory cache for the Binance USDT-pair catalogue. exchangeInfo +
# 24h-ticker is ~500KB combined; refreshing once an hour keeps the search
# endpoint responsive while staying way under Binance rate limits.
_PAIRS_CACHE: dict[str, Any] = {"data": None, "ts": 0.0}
_PAIRS_TTL = 3600.0   # 1 hour


async def _get_usdt_pairs() -> list[dict[str, Any]]:
    now = time.time()
    if _PAIRS_CACHE["data"] is not None and now - _PAIRS_CACHE["ts"] < _PAIRS_TTL:
        return _PAIRS_CACHE["data"]
    async with httpx.AsyncClient(timeout=15.0) as client:
        info = (await client.get(f"{settings.binance_rest}/api/v3/exchangeInfo")).json()
        tickers_raw = (await client.get(f"{settings.binance_rest}/api/v3/ticker/24hr")).json()
    vol_by_sym = {t["symbol"]: float(t.get("quoteVolume", 0) or 0) for t in tickers_raw}
    pairs: list[dict[str, Any]] = []
    for s in info.get("symbols", []):
        if (s.get("quoteAsset") == "USDT"
                and s.get("status") == "TRADING"
                and s.get("isSpotTradingAllowed", True)):
            sym = s["symbol"]
            pairs.append({
                "symbol": sym,
                "base": s["baseAsset"],
                "label": f"{s['baseAsset']}/USDT",
                "volume_24h": vol_by_sym.get(sym, 0.0),
            })
    pairs.sort(key=lambda p: -p["volume_24h"])  # highest-volume first
    _PAIRS_CACHE["data"] = pairs
    _PAIRS_CACHE["ts"] = now
    return pairs


@router.get("/symbols/search")
async def search_symbols(
    q: str = Query("", max_length=20, description="Substring to match against the pair symbol; case insensitive. Empty returns top-by-volume."),
    limit: int = Query(20, ge=1, le=100),
):
    """Lookup endpoint behind the Toolbar / AlertsTab coin picker. Returns
    the top USDT pairs from Binance matching `q` (substring match against
    SYMBOL). When `q` is empty the highest-volume pairs surface first so
    the picker shows a useful default list."""
    try:
        pairs = await _get_usdt_pairs()
    except Exception as e:
        raise HTTPException(502, f"Binance error: {e}")
    if q:
        q_upper = q.strip().upper()
        # Prefix-match wins over substring so 'BT' surfaces BTCUSDT before
        # other coins whose base happens to contain 'bt'.
        starts = [p for p in pairs if p["symbol"].startswith(q_upper)]
        contains = [p for p in pairs if (q_upper in p["symbol"]) and p not in starts]
        result = (starts + contains)[:limit]
    else:
        result = pairs[:limit]
    return {"q": q, "pairs": result}


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
