from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Binance public market-data endpoints. We default to the
    # `data-api.binance.vision` domain because it is data-only (no trading,
    # no auth) and is reachable from cloud-host IPs that the main api.binance.com
    # geo-blocks (HTTP 451). Override via env vars BINANCE_REST / BINANCE_WS.
    binance_rest: str = "https://data-api.binance.vision"
    binance_ws: str = "wss://data-stream.binance.vision/ws"

    default_symbol: str = "BTCUSDT"
    default_interval: str = "1m"

    # CORS — local dev (Vite) + production (same-origin so allow all).
    # Tighten this if you ever expose the API to a different frontend host.
    cors_origins: list[str] = ["*"]


settings = Settings()
