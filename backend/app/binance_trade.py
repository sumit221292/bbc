"""Binance Spot trading client — used by the auto-trade worker.

Implements just what we need: signed market entry, OCO bracket exit
(stop-loss + take-profit as one linked order), account balance lookup,
and cancel-all for the kill switch.

Auth is HMAC-SHA256 over the querystring with the secret as key. API key
goes in the X-MBX-APIKEY header. We never log secrets.

⚠️ All real money. Every function here can lose capital if misused.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
import urllib.parse

import httpx

log = logging.getLogger("btc.trade")

# Binance Spot REST. Note: this is the trading endpoint, NOT the data-only
# 'data-api.binance.vision' we use for klines elsewhere. Trading requires
# the main api.binance.com host.
BASE = "https://api.binance.com"


def _sign(params: dict, secret: str) -> str:
    """HMAC-SHA256 sign the querystring. Returns the signed querystring."""
    qs = urllib.parse.urlencode(params)
    sig = hmac.new(
        secret.encode("utf-8"),
        qs.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{qs}&signature={sig}"


async def get_balance(api_key: str, secret: str, asset: str) -> float:
    """Return free balance for `asset` (e.g. 'USDT')."""
    params = {"timestamp": int(time.time() * 1000), "recvWindow": 5000}
    signed = _sign(params, secret)
    url = f"{BASE}/api/v3/account?{signed}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(url, headers={"X-MBX-APIKEY": api_key})
        r.raise_for_status()
        for bal in r.json().get("balances", []):
            if bal["asset"] == asset:
                return float(bal["free"])
    return 0.0


async def get_exchange_info(symbol: str) -> dict:
    """Returns symbol's trading filters (LOT_SIZE step, PRICE_FILTER tick, MIN_NOTIONAL)."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"{BASE}/api/v3/exchangeInfo", params={"symbol": symbol})
        r.raise_for_status()
        data = r.json()
        if not data.get("symbols"):
            raise ValueError(f"symbol {symbol} not found")
        sym = data["symbols"][0]
        filters = {f["filterType"]: f for f in sym["filters"]}
        return {
            "step_size": float(filters["LOT_SIZE"]["stepSize"]),
            "min_qty": float(filters["LOT_SIZE"]["minQty"]),
            "tick_size": float(filters["PRICE_FILTER"]["tickSize"]),
            "min_notional": float(
                filters.get("NOTIONAL", filters.get("MIN_NOTIONAL", {})).get("minNotional", 10)
            ),
        }


def _round_to_step(value: float, step: float) -> float:
    """Floor `value` to nearest multiple of `step`. Binance rejects non-step quantities."""
    if step <= 0:
        return value
    return (int(value / step)) * step


async def place_market(api_key: str, secret: str, symbol: str, side: str, quantity: float) -> dict:
    """Place a MARKET order. Returns Binance's response dict."""
    params = {
        "symbol": symbol,
        "side": side.upper(),   # BUY or SELL
        "type": "MARKET",
        "quantity": f"{quantity:.8f}".rstrip("0").rstrip("."),
        "timestamp": int(time.time() * 1000),
        "recvWindow": 5000,
    }
    signed = _sign(params, secret)
    url = f"{BASE}/api/v3/order?{signed}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(url, headers={"X-MBX-APIKEY": api_key})
        if r.status_code >= 400:
            log.error("market order failed: %s", r.text)
        r.raise_for_status()
        return r.json()


async def place_oco(api_key: str, secret: str, symbol: str, side: str,
                    quantity: float, take_profit_price: float,
                    stop_price: float, stop_limit_price: float) -> dict:
    """Place an OCO bracket order: one side filled cancels the other.

    For an EXIT-side OCO after a BUY entry, `side` should be 'SELL':
      - take_profit_price: the limit-sell target (above current)
      - stop_price: the trigger that activates the stop-limit (below entry)
      - stop_limit_price: the actual sell price after the stop triggers
        (typically a tick or two below stop_price to ensure execution)

    For an EXIT after a SELL entry, side='BUY' and price relationships
    reverse (stop above entry, target below).
    """
    params = {
        "symbol": symbol,
        "side": side.upper(),
        "quantity": f"{quantity:.8f}".rstrip("0").rstrip("."),
        "price": f"{take_profit_price:.8f}".rstrip("0").rstrip("."),
        "stopPrice": f"{stop_price:.8f}".rstrip("0").rstrip("."),
        "stopLimitPrice": f"{stop_limit_price:.8f}".rstrip("0").rstrip("."),
        "stopLimitTimeInForce": "GTC",
        "timestamp": int(time.time() * 1000),
        "recvWindow": 5000,
    }
    signed = _sign(params, secret)
    url = f"{BASE}/api/v3/order/oco?{signed}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(url, headers={"X-MBX-APIKEY": api_key})
        if r.status_code >= 400:
            log.error("OCO order failed: %s", r.text)
        r.raise_for_status()
        return r.json()


async def cancel_all_open_orders(api_key: str, secret: str, symbol: str) -> dict:
    """Kill switch: cancel every open order on the symbol."""
    params = {
        "symbol": symbol,
        "timestamp": int(time.time() * 1000),
        "recvWindow": 5000,
    }
    signed = _sign(params, secret)
    url = f"{BASE}/api/v3/openOrders?{signed}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.delete(url, headers={"X-MBX-APIKEY": api_key})
        r.raise_for_status()
        return r.json()


async def test_credentials(api_key: str, secret: str) -> tuple[bool, str]:
    """Verify the API key works without doing anything risky.
    Calls /api/v3/account which requires a valid signed key."""
    try:
        params = {"timestamp": int(time.time() * 1000), "recvWindow": 5000}
        signed = _sign(params, secret)
        url = f"{BASE}/api/v3/account?{signed}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url, headers={"X-MBX-APIKEY": api_key})
            if r.status_code == 200:
                data = r.json()
                can_trade = data.get("canTrade", False)
                can_withdraw = data.get("canWithdraw", False)
                if not can_trade:
                    return False, "key valid but trading is disabled on this key"
                if can_withdraw:
                    return True, (
                        "⚠️ valid but WITHDRAWAL permission is enabled — "
                        "we strongly recommend disabling it for safety"
                    )
                return True, "✅ valid, trading enabled, withdrawal disabled"
            data = r.json()
            return False, data.get("msg", f"HTTP {r.status_code}")
    except Exception as e:
        return False, str(e)


def compute_quantity(capital_usd: float, risk_pct: float, entry: float,
                     stop: float, step_size: float, min_qty: float,
                     min_notional: float, max_position_usd: float) -> tuple[float, str]:
    """Position sizing: risk a fixed % of capital, never exceed max_position_usd.
    Returns (quantity, message). quantity == 0 means 'reject the trade'.
    """
    if entry <= 0 or stop <= 0:
        return 0.0, "invalid prices"
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return 0.0, "zero stop distance"

    risk_usd = capital_usd * risk_pct
    raw_qty = risk_usd / stop_dist
    notional = raw_qty * entry

    if notional > max_position_usd:
        raw_qty = max_position_usd / entry  # cap by max position
        notional = raw_qty * entry

    qty = _round_to_step(raw_qty, step_size)
    if qty < min_qty:
        return 0.0, f"quantity {qty} below min_qty {min_qty}"
    if qty * entry < min_notional:
        return 0.0, f"notional {qty * entry:.2f} below min_notional {min_notional}"

    return qty, f"qty={qty:.8f}, notional≈${qty * entry:.2f}, risk≈${risk_usd:.2f}"
