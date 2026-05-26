from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Which Binance market the app reads prices from: "spot" or
    # "futures" (USDT-M perpetuals, what TradingView calls BTCUSDT.P).
    #
    # Defaults to "spot" because Binance Futures (fapi.binance.com)
    # geo-blocks cloud-host IPs that the Vision data mirror doesn't,
    # so Railway / GCP / most PaaS hosts get HTTP 451 on direct
    # fapi calls. To switch to Futures: deploy the Cloudflare Worker
    # proxy in cloudflare-worker/ (free, runs on edge IPs Binance
    # doesn't block), then on Railway set:
    #   BINANCE_MARKET=futures
    #   BINANCE_FUTURES_REST=https://<your-worker>.workers.dev
    # Locally (from a non-blocked IP) just BINANCE_MARKET=futures works.
    binance_market: str = "spot"

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
