import os
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

# Live-price cache for the live-PnL UI under TradesTab. /ticker/price is
# a single ~80KB request that lists every symbol with no extra data, so
# we hit it once every 10s and serve every concurrent caller from the
# cached dict.
_PRICES_CACHE: dict[str, Any] = {"data": None, "ts": 0.0}
_PRICES_TTL = 10.0

# Hard floor on last price for inclusion in the picker / search results.
# Sub-$1 coins (DOGE 0.10579, PEPE 0.0000123, SHIB 0.00000789) have tick
# sizes that wreck Confluence's median entry/stop/target maths -- a 1
# tick slip on PEPE is a multi-percent move, so the strategy's RR floor
# silently collapses on real fills. The user asked for $1+ only.
SYMBOL_MIN_PRICE = float(os.environ.get("SYMBOL_MIN_PRICE", "1.0"))

# Stablecoins (USDC/BUSD/etc) trade at ~$1 so they pass the price gate
# but have no useful directional movement to trade. Filter them out at
# the source.
_STABLE_BASES = {"USDC", "BUSD", "TUSD", "FDUSD", "USDP", "DAI", "USDS", "PYUSD"}


async def _get_usdt_pairs() -> list[dict[str, Any]]:
    now = time.time()
    if _PAIRS_CACHE["data"] is not None and now - _PAIRS_CACHE["ts"] < _PAIRS_TTL:
        return _PAIRS_CACHE["data"]
    base = f"{settings.market_rest}{settings.market_api_prefix}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        info = (await client.get(f"{base}/exchangeInfo")).json()
        tickers_raw = (await client.get(f"{base}/ticker/24hr")).json()
    vol_by_sym = {t["symbol"]: float(t.get("quoteVolume", 0) or 0) for t in tickers_raw}
    price_by_sym = {t["symbol"]: float(t.get("lastPrice", 0) or 0) for t in tickers_raw}
    pairs: list[dict[str, Any]] = []
    for s in info.get("symbols", []):
        if s.get("quoteAsset") != "USDT": continue
        if s.get("status") != "TRADING": continue
        # Spot has isSpotTradingAllowed; Futures has contractType.
        # Filter perpetuals only on the Futures side -- skip dated
        # delivery contracts like BTCUSDT_240927.
        if settings.is_futures:
            if s.get("contractType") != "PERPETUAL": continue
        else:
            if not s.get("isSpotTradingAllowed", True): continue
        sym = s["symbol"]
        # Sub-$1 floor: precision blows up trade execution at penny prices.
        if price_by_sym.get(sym, 0.0) < SYMBOL_MIN_PRICE: continue
        # Drop stablecoin-quoted-against-USDT pairs (USDC/USDT etc).
        if s["baseAsset"] in _STABLE_BASES: continue
        pairs.append({
            "symbol": sym,
            "base": s["baseAsset"],
            "label": f"{s['baseAsset']}/USDT",
            "volume_24h": vol_by_sym.get(sym, 0.0),
            "price": price_by_sym.get(sym, 0.0),
        })
    pairs.sort(key=lambda p: -p["volume_24h"])  # highest-volume first
    _PAIRS_CACHE["data"] = pairs
    _PAIRS_CACHE["ts"] = now
    return pairs


async def _get_all_prices() -> dict[str, float]:
    """Cached snapshot of every Binance symbol's last trade price.
    Hits the same market endpoint as the rest of the data layer so the
    UI's live PnL matches what the user sees on Binance Futures."""
    now = time.time()
    cached = _PRICES_CACHE["data"]
    if cached is not None and now - _PRICES_CACHE["ts"] < _PRICES_TTL:
        return cached
    url = f"{settings.market_rest}{settings.market_api_prefix}/ticker/price"
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(url)
        r.raise_for_status()
        data = r.json()
    prices = {t["symbol"]: float(t["price"]) for t in data}
    _PRICES_CACHE["data"] = prices
    _PRICES_CACHE["ts"] = now
    return prices


@router.get("/info")
async def market_info():
    """Which Binance market the app is reading from. Frontend uses this
    to render a "FUTURES" / "SPOT" badge so the user knows which set of
    prices they're looking at."""
    return {
        "market": "futures" if settings.is_futures else "spot",
        "rest": settings.market_rest,
        "api_prefix": settings.market_api_prefix,
    }


@router.get("/prices")
async def get_prices(
    symbols: str = Query("", description="Comma-separated symbol list; empty returns every USDT pair."),
):
    """Latest trade prices for live-PnL UI. Cached 10s -- well within
    Binance limits and fresh enough to feel real-time on the TradesTab
    OPEN rows."""
    try:
        all_prices = await _get_all_prices()
    except Exception as e:
        raise HTTPException(502, f"Binance error: {e}")
    if not symbols:
        return {"prices": all_prices}
    wanted = {s.strip().upper() for s in symbols.split(",") if s.strip()}
    return {"prices": {s: all_prices[s] for s in wanted if s in all_prices}}


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
