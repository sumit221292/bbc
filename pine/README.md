# Pine Script ports

TradingView Pine Script versions of our strategies. These are **drop-in
copies** of the Python evaluators in `backend/app/strategies/` — same
indicators, same thresholds, same regime logic.

## Why a separate port?

Pine Script runs **inside TradingView's chart**. It does not touch our
backend, our DB, or the Telegram worker. Use it when you want:

- **Visual overlay** of strategy signals directly on TradingView with all
  of TV's drawing/indicator tools.
- **Manual review** of historical trades on a clean professional chart.
- **TV-native alerts** (mobile push, email, sound) — separate from our
  Telegram worker.

These ports are **not** how the live Telegram bot or auto-trader work —
those still come from the Python worker on Railway.

## Files

| File | Source | Strategy |
|---|---|---|
| `champion.pine` | `backend/app/strategies/champion.py` | ★★★ Champion (Adaptive Regime) |

## How to load into TradingView

1. Open any chart at https://in.tradingview.com (e.g. your `j9RDfUl2`).
2. Top toolbar -> **Pine Editor** (bottom panel) or the `{}` icon.
3. Click **New** -> **Indicator**. A scratch template opens.
4. Select all (`Ctrl+A`), delete, paste the contents of `champion.pine`.
5. Click **Save** -> name it "Champion (Adaptive Regime)".
6. Click **Add to chart**.

It now lives under **Indicators -> My Scripts** for one-click attach to
any chart later.

## Tuning to match the live Python version

The defaults already match `champion.py` v10 exactly. Recommended:

- **Timeframe**: 1h or 4h (matches Python tuning).
- **Symbol**: BINANCE:BTCUSDT (the live worker uses Binance candles too).

If you change a parameter in TV, the signals will diverge from what the
backend fires. Keep them in sync if you want the chart to match the
Telegram alerts.

## What this script does NOT do

- Does not send alerts to our Telegram bot. (Pine alerts go to TV's own
  notification channels.)
- Does not save trades to our SQLite DB.
- Does not trigger auto-trade on Binance.

If you want TV-fired signals to flow into our backend, ask for the
`/api/tv-webhook` endpoint — TradingView alerts can POST to any URL, so
the worker could ingest TV-side signals just like its own.
