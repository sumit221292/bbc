from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Which Binance market the app reads prices from: "spot" (default
    # was) or "futures" (USDT-M perpetuals, what TradingView calls
    # BTCUSDT.P). Defaults to "futures" because that's what users
    # actually trade -- spot/futures prices diverge during volatility
    # and the resulting SL/TP mismatch was the user's #1 complaint.
    # Override with BINANCE_MARKET=spot to revert.
    binance_market: str = "futures"

    # Spot endpoints. data-api.binance.vision is the data-only mirror
    # reachable from cloud-host IPs that geo-block api.binance.com (451).
    binance_rest: str = "https://data-api.binance.vision"
    binance_ws: str = "wss://data-stream.binance.vision/ws"

    # Futures USDT-M endpoints. No public data-only mirror exists for
    # futures; if Railway 451s on this, set BINANCE_MARKET=spot to fall
    # back. fapi.binance.com is normally reachable from Railway / GCP.
    binance_futures_rest: str = "https://fapi.binance.com"
    binance_futures_ws: str = "wss://fstream.binance.com/ws"

    default_symbol: str = "BTCUSDT"
    default_interval: str = "1m"

    # CORS — local dev (Vite) + production (same-origin so allow all).
    # Tighten this if you ever expose the API to a different frontend host.
    cors_origins: list[str] = ["*"]

    # ---- Market routing helpers (consumed by binance.py + routers) ----
    # These let every caller stay market-agnostic: just use settings.market_*
    # without knowing which endpoint family is active.
    @property
    def is_futures(self) -> bool:
        return self.binance_market.lower() == "futures"

    @property
    def market_rest(self) -> str:
        return self.binance_futures_rest if self.is_futures else self.binance_rest

    @property
    def market_ws(self) -> str:
        return self.binance_futures_ws if self.is_futures else self.binance_ws

    @property
    def market_api_prefix(self) -> str:
        """REST path prefix that prepends every data endpoint.
        Spot uses /api/v3, Futures uses /fapi/v1."""
        return "/fapi/v1" if self.is_futures else "/api/v3"


settings = Settings()
