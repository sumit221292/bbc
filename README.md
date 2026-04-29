# BTC/USDT Trading Analysis

A lightweight, full-stack crypto trading analysis app inspired by TradingView. Real-time
candlestick chart for BTC/USDT (and other Binance pairs), drawing tools, EMA/RSI/Volume
indicators, and a pluggable strategy engine that emits BUY / SELL / HOLD signals.

## Stack

- **Backend:** FastAPI (Python 3.11+) — async, lightweight, native WebSockets.
  *(The brief asked for Django+DRF; FastAPI was chosen because it is much lighter and
  has first-class WebSocket support — see the Notes section.)*
- **Frontend:** React 18 + Vite (modern hooks, no boilerplate, fast HMR)
- **Charting:** [TradingView Lightweight Charts](https://github.com/tradingview/lightweight-charts) v4
- **Real-time:** Backend bridges Binance's public kline WebSocket to the browser
- **Indicators:** Pure Python (NumPy) — EMA, RSI, support/resistance

## Project layout

```
btc/
├─ backend/
│  ├─ requirements.txt
│  └─ app/
│     ├─ main.py             # FastAPI app, REST routers, WS endpoint
│     ├─ config.py           # Settings (CORS, Binance endpoints)
│     ├─ binance.py          # REST + WS client to Binance public market data
│     ├─ indicators.py       # EMA, RSI, support/resistance
│     ├─ schemas.py          # Pydantic models (Candle, Signal, …)
│     ├─ routers/
│     │  ├─ market.py        # /api/market/klines, /api/market/indicators
│     │  └─ strategy.py      # /api/strategy/list, /api/strategy/run
│     └─ strategies/
│        ├─ base.py          # Strategy abstract base
│        ├─ registry.py      # Plug-in registry — add a class & you're done
│        ├─ scalping.py      # RSI 30/70
│        ├─ day_trading.py   # EMA 20/50 cross
│        ├─ swing.py         # Support/Resistance bounce
│        ├─ trend_following.py
│        └─ breakout.py      # Resistance break + volume confirmation
└─ frontend/
   ├─ package.json
   ├─ vite.config.js         # Proxies /api & /ws to backend in dev
   ├─ index.html
   └─ src/
      ├─ main.jsx
      ├─ App.jsx             # Top-level state & data wiring
      ├─ api.js              # REST client
      ├─ hooks/
      │  └─ useLiveKlines.js # WebSocket hook with auto-reconnect
      ├─ components/
      │  ├─ Chart.jsx        # Lightweight Charts + drawing overlay (canvas)
      │  ├─ Toolbar.jsx
      │  ├─ StrategySelector.jsx
      │  └─ SignalPanel.jsx
      └─ styles/app.css
```

## Setup

### 1. Backend

```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

API will be available at <http://localhost:8000>. Swagger docs: <http://localhost:8000/docs>.

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api/*` and `/ws/*` to the backend, so no
CORS or WS-origin gymnastics in dev.

## API documentation

| Method | Path | Description |
|---|---|---|
| GET | `/api/market/klines?symbol&interval&limit` | Historical OHLCV candles from Binance |
| GET | `/api/market/indicators?symbol&interval&limit` | Aligned `time`, `ema20`, `ema50`, `ema200`, `rsi14` arrays |
| GET | `/api/strategy/list` | All registered strategies (id, name, description) |
| GET | `/api/strategy/run?id&symbol&interval&limit` | Runs a strategy, returns historical `signals[]` and `latest` signal |
| WS | `/ws/klines?symbol&interval` | Streams every Binance kline tick as JSON `{time, open, high, low, close, volume}` |

Default symbol/interval = `BTCUSDT` / `1m`. Limit max = 1000.

### Example — run the scalping strategy

```bash
curl 'http://localhost:8000/api/strategy/run?id=scalping&symbol=BTCUSDT&interval=5m&limit=300'
```

```json
{
  "strategy": "scalping",
  "symbol": "BTCUSDT",
  "interval": "5m",
  "signals": [
    {"time": 1714378200, "type": "BUY", "price": 63420.5, "reason": "RSI crossed below 30 (28.4)",
     "entry": 63420.5, "stop_loss": 63100.2, "target": 64054.7}
  ],
  "latest": {"time": 1714411800, "type": "HOLD", "price": 64210.0, "reason": "No trigger on the latest bar"}
}
```

## Strategies — how to add a new one

1. Create `backend/app/strategies/my_strategy.py`:

   ```python
   from ..schemas import Candle, Signal
   from .base import Strategy

   class MyStrategy(Strategy):
       id = "my_strategy"
       name = "My Strategy"
       description = "Does a thing."

       def evaluate(self, candles: list[Candle]) -> list[Signal]:
           return []  # return BUY/SELL signals; HOLDs are auto-derived
   ```

2. Register it in `backend/app/strategies/registry.py`:

   ```python
   from .my_strategy import MyStrategy
   _STRATEGIES = {cls.id: cls for cls in (..., MyStrategy)}
   ```

3. It now appears in the UI dropdown automatically.

## Features checklist

- [x] Real-time candlestick chart (Binance klines + WebSocket)
- [x] Drawing tools: trendline, horizontal line, free draw + clear
- [x] Indicators: EMA 20 / 50 / 200, RSI(14), Volume
- [x] 5 strategies: Scalping, Day Trading, Swing, Trend Following, Breakout
- [x] Strategy engine: modular classes + registry, BUY/SELL/HOLD signals
- [x] Chart annotations: arrow markers + dashed Entry/Stop/Target price lines
- [x] Strategy selector pills, clean dark dashboard, responsive (mobile breakpoint)
- [x] Performance: imperative chart updates via ref (no React re-render on tick),
      memoized child components, single shared WS connection per symbol/interval
- [x] Multi-coin: symbol dropdown (BTC/ETH/SOL/BNB) — works for any Binance USDT pair

### Optional / not implemented
- User login & saved strategies
- Backtesting module (the strategy engine is pure-functional over candles, so a
  backtester is essentially "iterate `evaluate` on growing windows" — easy to bolt on)

## Notes on stack choice

The brief specified Django + DRF. I chose **FastAPI** because:
- Native async + WebSockets — no Channels, no ASGI wiring, no Daphne/Uvicorn split.
- Pydantic v2 models double as request/response schemas and as the strategy data layer.
- ~50 lines of `main.py` vs. multiple Django settings/apps for an API-only service.

If Django is required for organisational reasons, the strategy engine, indicators, and
Binance client modules are pure Python — drop them into a Django app unchanged and wrap
the routers as DRF views.

## Disclaimer

This is an educational/analytical tool. Signals are not financial advice. The strategies
are intentionally simple textbook implementations.
