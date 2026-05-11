"""Always-on Telegram alert worker.

Runs in the background as an asyncio task started from main.py. Every 60s
it walks each active subscription, evaluates the strategy at its preferred
timeframe, and sends a Telegram message if a NEW open trade has appeared
since the last poll.

Persistence: alerts_config.json next to the backend package. On Railway
this survives in-container restarts but resets on full redeploys -- the
frontend re-syncs its localStorage on first load so this is not an issue.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Optional

import httpx
from pydantic import BaseModel, Field

from datetime import datetime, timezone

from .binance import fetch_klines
from .binance_trade import (
    cancel_all_open_orders, compute_quantity, get_exchange_info,
    place_market, place_oco,
)
from .multi_tf import MTFContext
from .smc_mtf import SMCMTFContext
from .strategies import (
    get_strategy, is_mtf, is_smc_mtf, list_mtf_metas, list_strategies,
    run_mtf, run_smc_mtf,
)
from .trade_status import annotate

log = logging.getLogger("btc.alerts")

CONFIG_PATH = Path(__file__).resolve().parent.parent / "alerts_config.json"
POLL_SECONDS = 60
DEFAULT_SYMBOL = "BTCUSDT"

_lock = asyncio.Lock()


class Subscription(BaseModel):
    strategy_id: str
    interval: Optional[str] = None  # None = use strategy default


class AutoTradeConfig(BaseModel):
    """Live auto-execution settings — every safety knob defaults to OFF/conservative."""
    enabled: bool = False             # master switch (default OFF)
    api_key: str = ""
    api_secret: str = ""
    capital_usd: float = 100.0        # paper-low default
    risk_pct: float = 0.01            # 1% per trade (hard-capped to 0.05 below)
    max_position_usd: float = 500.0   # hard cap per trade
    max_trades_per_day: int = 5
    max_daily_loss_pct: float = 0.05  # halt if -5% intraday
    confirmation: str = ""            # must equal CONFIRM_PHRASE to enable
    # Per-strategy whitelist: only these strategy IDs are allowed to auto-trade.
    # Empty list = NO auto-trade even if enabled.
    allowed_strategies: list[str] = Field(default_factory=list)
    # Daily counters (reset at UTC midnight by alert_loop)
    trades_today: int = 0
    loss_today_pct: float = 0.0
    day_started: int = 0              # UTC midnight of the current trade day
    last_trade_error: str = ""
    halted_reason: str = ""           # populated if circuit breaker fired


CONFIRM_PHRASE = "I UNDERSTAND THE RISKS"
MAX_RISK_PCT = 0.05  # absolute cap regardless of user input


class AlertConfig(BaseModel):
    token: str = ""
    chat_id: str = ""
    enabled: bool = False
    symbol: str = DEFAULT_SYMBOL
    subscriptions: list[Subscription] = Field(default_factory=list)
    # last seen signal time per strategy_id (epoch seconds)
    last_seen: dict[str, int] = Field(default_factory=dict)
    last_poll: int = 0
    last_error: str = ""
    auto_trade: AutoTradeConfig = Field(default_factory=AutoTradeConfig)


def _default_interval(strategy_id: str) -> str:
    if is_smc_mtf(strategy_id):
        return "5m"
    if is_mtf(strategy_id):
        return "1h"
    if strategy_id == "smc_momentum":
        return "15m"
    return "1h"


def _strategy_name(strategy_id: str) -> str:
    if is_mtf(strategy_id):
        for m in list_mtf_metas():
            if m.id == strategy_id:
                return m.name
    try:
        return get_strategy(strategy_id).name
    except KeyError:
        return strategy_id


async def load_config() -> AlertConfig:
    async with _lock:
        if not CONFIG_PATH.exists():
            return AlertConfig()
        try:
            return AlertConfig(**json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception:
            log.exception("alerts config load failed; resetting")
            return AlertConfig()


async def save_config(cfg: AlertConfig) -> None:
    async with _lock:
        CONFIG_PATH.write_text(cfg.model_dump_json(indent=2), encoding="utf-8")


async def send_telegram(token: str, chat_id: str, text: str) -> tuple[bool, str]:
    if not token or not chat_id:
        return False, "missing token or chat_id"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, json={
                "chat_id": chat_id, "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            })
            data = r.json()
            if data.get("ok"):
                return True, ""
            return False, data.get("description", "unknown error")
    except Exception as e:
        return False, str(e)


def _verify_direction(sig) -> tuple[str, bool]:
    """Cross-check the signal's declared type against its stop/target geometry.

    For BUY: stop < entry < target.
    For SELL: target < entry < stop.

    Returns (effective_type, was_corrected). If the geometry contradicts the
    declared type, we trust the geometry and flag the signal as corrected so
    the alert message can warn the user.
    """
    if sig.entry is None or sig.stop_loss is None or sig.target is None:
        return sig.type, False
    e, sl, tp = sig.entry, sig.stop_loss, sig.target
    geometry_buy = sl < e < tp
    geometry_sell = tp < e < sl
    if sig.type == "BUY" and not geometry_buy:
        return ("SELL" if geometry_sell else sig.type), True
    if sig.type == "SELL" and not geometry_sell:
        return ("BUY" if geometry_buy else sig.type), True
    return sig.type, False


def _format_signal(symbol: str, name: str, sig) -> str:
    effective_type, corrected = _verify_direction(sig)

    sign = "🟢" if effective_type == "BUY" else "🔴" if effective_type == "SELL" else "⏸"
    action = (
        "BUY (Khareedo)" if effective_type == "BUY"
        else "SELL (Becho)" if effective_type == "SELL"
        else "WAIT"
    )
    # Markdown-escape the strategy name (Python 3.11 disallows backslashes
    # inside f-string expressions, so do this on a separate line).
    safe_name = name.replace("*", "").replace("_", "\\_")
    parts = [
        f"{sign} *{action}* — `{symbol}`",
        f"*Strategy:* {safe_name}",
    ]
    if corrected:
        parts.append(
            "⚠️ _Direction was corrected from the strategy's declared "
            f"{sig.type} to match the actual stop/target geometry._"
        )
    if sig.entry is not None:
        parts.append(f"*Entry:* `${sig.entry:,.2f}`")
    if sig.stop_loss is not None and sig.entry:
        # Directional arrow leaves no doubt: SL ↓ for BUY (below), SL ↑ for SELL (above).
        sl_arrow = "↓" if sig.stop_loss < sig.entry else "↑"
        loss_pct = abs(sig.stop_loss - sig.entry) / sig.entry * 100
        parts.append(f"*Stop {sl_arrow}:* `${sig.stop_loss:,.2f}` (-{loss_pct:.2f}%)")
    if sig.target is not None and sig.entry:
        tp_arrow = "↑" if sig.target > sig.entry else "↓"
        prof_pct = abs(sig.target - sig.entry) / sig.entry * 100
        parts.append(f"*Target {tp_arrow}:* `${sig.target:,.2f}` (+{prof_pct:.2f}%)")
    if sig.entry and sig.stop_loss and sig.target:
        risk = abs(sig.entry - sig.stop_loss)
        if risk > 0:
            rr = abs(sig.target - sig.entry) / risk
            parts.append(f"*RR:* 1 : {rr:.2f}")
    return "\n".join(parts)


async def _evaluate_subscription(sub: Subscription, symbol: str):
    """Returns (latest_open_signal_or_None, strategy_name)."""
    sid = sub.strategy_id
    interval = sub.interval or _default_interval(sid)
    name = _strategy_name(sid)

    if is_smc_mtf(sid):
        c5, c15, c1h = await asyncio.gather(
            fetch_klines(symbol, "5m", 1000),
            fetch_klines(symbol, "15m", 500),
            fetch_klines(symbol, "1h", 300),
        )
        ctx = SMCMTFContext(candles_5m=c5, candles_15m=c15, candles_1h=c1h)
        signals = annotate(run_smc_mtf(sid, ctx, start_idx=60), c5)
    elif is_mtf(sid):
        c1h, c4h, c1d = await asyncio.gather(
            fetch_klines(symbol, "1h", 1000),
            fetch_klines(symbol, "4h", 1000),
            fetch_klines(symbol, "1d", 1000),
        )
        ctx = MTFContext(candles_1h=c1h, candles_4h=c4h, candles_1d=c1d)
        signals = annotate(run_mtf(sid, ctx, start_idx=50), c1h)
    else:
        strat = get_strategy(sid)
        candles = await fetch_klines(symbol, interval, 500)
        signals = annotate(strat.evaluate(candles), candles)

    open_signals = [s for s in signals if s.status == "OPEN"]
    return (open_signals[-1] if open_signals else None), name


def _utc_midnight(ts: int) -> int:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    midnight = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(midnight.timestamp())


async def _maybe_auto_execute(cfg: AlertConfig, sub: Subscription, sig) -> str | None:
    """Place a real Binance order for this signal if all safety conditions pass.
    Returns a human-readable status string for the Telegram message footer,
    or None if auto-trade is not active for this signal."""
    at = cfg.auto_trade

    # Hard gates — fail closed.
    if not at.enabled:
        return None
    if at.confirmation != CONFIRM_PHRASE:
        return "auto-trade: skipped (confirmation phrase missing)"
    if not at.api_key or not at.api_secret:
        return "auto-trade: skipped (no API key)"
    if sub.strategy_id not in at.allowed_strategies:
        return f"auto-trade: skipped ({sub.strategy_id} not whitelisted)"
    if at.halted_reason:
        return f"auto-trade: HALTED — {at.halted_reason}"

    # Daily counters
    now = int(time.time())
    today_start = _utc_midnight(now)
    if at.day_started != today_start:
        at.trades_today = 0
        at.loss_today_pct = 0.0
        at.day_started = today_start

    if at.trades_today >= at.max_trades_per_day:
        return f"auto-trade: skipped (daily cap {at.max_trades_per_day} hit)"
    if at.loss_today_pct >= at.max_daily_loss_pct:
        at.halted_reason = f"daily loss limit -{at.loss_today_pct*100:.2f}% hit"
        return f"auto-trade: HALTED — {at.halted_reason}"
    if sig.entry is None or sig.stop_loss is None or sig.target is None:
        return "auto-trade: skipped (incomplete signal levels)"

    # Sizing
    risk = min(at.risk_pct, MAX_RISK_PCT)
    try:
        info = await get_exchange_info(cfg.symbol)
    except Exception as e:
        at.last_trade_error = f"exchange info failed: {e}"
        return f"auto-trade: skipped (exchange info: {e})"

    qty, msg = compute_quantity(
        capital_usd=at.capital_usd, risk_pct=risk,
        entry=sig.entry, stop=sig.stop_loss,
        step_size=info["step_size"], min_qty=info["min_qty"],
        min_notional=info["min_notional"],
        max_position_usd=at.max_position_usd,
    )
    if qty <= 0:
        return f"auto-trade: skipped ({msg})"

    # Place entry
    entry_side = "BUY" if sig.type == "BUY" else "SELL"
    exit_side = "SELL" if sig.type == "BUY" else "BUY"
    try:
        log.info("[AUTO-TRADE] placing %s %s qty=%s (%s)",
                 entry_side, cfg.symbol, qty, msg)
        entry_resp = await place_market(at.api_key, at.api_secret, cfg.symbol, entry_side, qty)
    except Exception as e:
        at.last_trade_error = f"entry failed: {e}"
        log.error("[AUTO-TRADE] entry failed: %s", e)
        return f"auto-trade: ENTRY FAILED — {e}"

    # Place OCO bracket exit (stop + target). If this fails we have a naked
    # position — log loudly and Telegram-warn the user.
    tick = info["tick_size"]
    # Stop-limit fires a tick or two beyond stop_price so it actually fills.
    if entry_side == "BUY":
        stop_limit = sig.stop_loss - tick * 2
    else:
        stop_limit = sig.stop_loss + tick * 2
    try:
        oco_resp = await place_oco(
            at.api_key, at.api_secret, cfg.symbol, exit_side, qty,
            take_profit_price=sig.target,
            stop_price=sig.stop_loss,
            stop_limit_price=stop_limit,
        )
    except Exception as e:
        at.last_trade_error = f"OCO failed: {e}"
        log.error("[AUTO-TRADE] OCO failed — position is UNPROTECTED: %s", e)
        return (
            f"⚠️ auto-trade: ENTRY FILLED but OCO failed ({e}). "
            "Position is UNPROTECTED. Place manual stop+target NOW."
        )

    at.trades_today += 1
    at.last_trade_error = ""
    fill_price = float(entry_resp.get("fills", [{}])[0].get("price", sig.entry))
    return (
        f"✅ auto-trade: filled {entry_side} {qty} @ ${fill_price:.2f} "
        f"(daily {at.trades_today}/{at.max_trades_per_day})"
    )


async def alert_loop():
    """Background task, started from main.py on startup."""
    log.info("alert worker started; polling every %ss", POLL_SECONDS)
    while True:
        try:
            cfg = await load_config()
            if cfg.enabled and cfg.token and cfg.chat_id and cfg.subscriptions:
                changed = False
                for sub in cfg.subscriptions:
                    try:
                        latest, name = await _evaluate_subscription(sub, cfg.symbol)
                    except Exception as e:
                        log.warning("eval %s failed: %s", sub.strategy_id, e)
                        continue
                    if latest is None:
                        continue
                    last_seen = cfg.last_seen.get(sub.strategy_id, 0)
                    if latest.time > last_seen:
                        # Loud audit log for every signal — captures any future
                        # direction-mismatch evidence in raw form.
                        log.info(
                            "[ALERT] %s type=%s entry=%s stop=%s target=%s reason=%r",
                            sub.strategy_id, latest.type, latest.entry,
                            latest.stop_loss, latest.target, latest.reason,
                        )
                        eff_type, corrected = _verify_direction(latest)
                        if corrected:
                            log.error(
                                "[DIRECTION-MISMATCH] %s declared %s but geometry "
                                "indicates %s (entry=%s stop=%s target=%s)",
                                sub.strategy_id, latest.type, eff_type,
                                latest.entry, latest.stop_loss, latest.target,
                            )

                        # Try auto-execution BEFORE the Telegram message so
                        # the message can reflect the outcome.
                        trade_status = await _maybe_auto_execute(cfg, sub, latest)
                        msg = _format_signal(cfg.symbol, name, latest)
                        if trade_status:
                            msg = msg + "\n\n" + trade_status
                        ok, err = await send_telegram(cfg.token, cfg.chat_id, msg)
                        if ok:
                            cfg.last_seen[sub.strategy_id] = latest.time
                            changed = True
                            log.info("sent alert for %s @ %s", sub.strategy_id, latest.time)
                        else:
                            cfg.last_error = f"{sub.strategy_id}: {err}"
                            changed = True
                            log.warning("send failed: %s", err)
                cfg.last_poll = int(time.time())
                if changed or cfg.last_poll - getattr(cfg, "last_poll", 0) > 60:
                    await save_config(cfg)
        except Exception:
            log.exception("alert_loop tick crashed; will retry")
        await asyncio.sleep(POLL_SECONDS)
