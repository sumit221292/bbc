from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Binance public endpoints — no API key required for market data.
    binance_rest: str = "https://api.binance.com"
    binance_ws: str = "wss://stream.binance.com:9443/ws"

    default_symbol: str = "BTCUSDT"
    default_interval: str = "1m"

    # CORS — local dev (Vite) + production (same-origin so allow all).
    # Tighten this if you ever expose the API to a different frontend host.
    cors_origins: list[str] = ["*"]


settings = Settings()
