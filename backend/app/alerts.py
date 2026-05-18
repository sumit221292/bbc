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
    cancel_all_open_orders, compute_quantity, get_balance, get_exchange_info,
    place_market, place_oco,
)
from .multi_tf import MTFContext
from .smc_mtf import SMCMTFContext
from .strategies import (
    get_strategy, is_mtf, is_smc_mtf, list_mtf_metas, list_strategies,
    run_mtf, run_smc_mtf,
)
from .schemas import Signal
from .trade_status import annotate
from . import trade_store

log = logging.getLogger("btc.alerts")

# Legacy JSON config (pre-DB). Imported into kv_store on first load then
# left in place untouched so a manual rollback is always possible.
LEGACY_CONFIG_PATH = Path(__file__).resolve().parent.parent / "alerts_config.json"
CONFIG_KEY = "alert_config"
POLL_SECONDS = 60
DEFAULT_SYMBOL = "BTCUSDT"

_lock = asyncio.Lock()


class Subscription(BaseModel):
    strategy_id: str
    interval: Optional[str] = None  # None = use strategy default


class OpenPosition(BaseModel):
    """A single live position. Only one per symbol at a time (no averaging)."""
    side: str                  # 'LONG' or 'SHORT'
    qty: float
    entry: float
    stop: float
    target: float
    strategy_id: str
    opened_at: int             # epoch seconds


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
    # Smart trade manager state
    current_position: Optional[OpenPosition] = None
    # Daily counters (reset at UTC midnight by alert_loop)
    trades_today: int = 0
    loss_today_pct: float = 0.0
    day_started: int = 0              # UTC midnight of the current trade day
    last_trade_error: str = ""
    halted_reason: str = ""           # populated if circuit breaker fired


CONFIRM_PHRASE = "I UNDERSTAND THE RISKS"
MAX_RISK_PCT = 0.05  # absolute cap regardless of user input


class PendingSignal(BaseModel):
    """A signal we've notified about whose outcome we still need to follow up on."""
    time: int          # signal's candle time (matches sig.time)
    side: str          # BUY / SELL
    entry: float
    stop: float
    target: float


class AlertConfig(BaseModel):
    token: str = ""
    # Legacy single chat_id (kept for backward compat).
    chat_id: str = ""
    # New multi-chat field — every notification is broadcast to every id here.
    chat_ids: list[str] = Field(default_factory=list)
    enabled: bool = False
    # Auto-trade target symbol. Always single because the auto-trader holds
    # one position at a time on one account. Signal generation can run on
    # many coins (see `symbols`), but Binance orders only fire here.
    symbol: str = DEFAULT_SYMBOL
    # Multi-coin watchlist. The worker fires signals + Telegram alerts +
    # DB inserts for every (symbol, subscription) pair every tick. Defaults
    # to [symbol] for backward compat with old single-coin configs.
    symbols: list[str] = Field(default_factory=lambda: [DEFAULT_SYMBOL])
    subscriptions: list[Subscription] = Field(default_factory=list)
    # last seen signal time, keyed by "symbol::strategy_id" composite so
    # different coins do not stomp each other's notification cursor.
    last_seen: dict[str, int] = Field(default_factory=dict)
    # Per (symbol, strategy): the most recently NOTIFIED signal whose
    # outcome (WIN/LOSS) we still need to send a follow-up Telegram for.
    pending_close: dict[str, PendingSignal] = Field(default_factory=dict)
    last_poll: int = 0
    last_error: str = ""
    auto_trade: AutoTradeConfig = Field(default_factory=AutoTradeConfig)


def _state_key(symbol: str, strategy_id: str) -> str:
    """Composite key for per-(symbol, strategy) tracking dicts. Using `::`
    as the separator because Binance symbols and strategy ids never
    contain it, so the split is unambiguous."""
    return f"{symbol}::{strategy_id}"


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


def _migrate_legacy(cfg: AlertConfig) -> AlertConfig:
    """One-shot upgrade for configs saved before multi-coin support:
      - If `symbols` is empty/missing, seed it from `symbol`.
      - Convert flat last_seen/pending_close keys ("champion") to the new
        composite form ("BTCUSDT::champion"). Old keys are dropped after
        translation; nothing else needs to do this lookup."""
    if not cfg.symbols:
        cfg.symbols = [cfg.symbol or DEFAULT_SYMBOL]

    if cfg.last_seen and not any("::" in k for k in cfg.last_seen):
        cfg.last_seen = {
            _state_key(cfg.symbol, sid): ts for sid, ts in cfg.last_seen.items()
        }
    if cfg.pending_close and not any("::" in k for k in cfg.pending_close):
        cfg.pending_close = {
            _state_key(cfg.symbol, sid): ps for sid, ps in cfg.pending_close.items()
        }
    return cfg


async def load_config() -> AlertConfig:
    """Read the alert config from kv_store. Falls back to the legacy JSON
    file once (and writes it into the DB) so users who upgrade don't lose
    their Telegram setup."""
    async with _lock:
        blob = trade_store.get_kv(CONFIG_KEY)
        if blob is not None:
            try:
                return _migrate_legacy(AlertConfig(**blob))
            except Exception:
                log.exception("alerts config (DB) corrupt; resetting")
                return AlertConfig()

        # One-shot migration from the JSON file.
        if LEGACY_CONFIG_PATH.exists():
            try:
                data = json.loads(LEGACY_CONFIG_PATH.read_text(encoding="utf-8"))
                cfg = _migrate_legacy(AlertConfig(**data))
                trade_store.set_kv(CONFIG_KEY, cfg.model_dump(mode="json"))
                log.info("alerts config migrated from JSON file to DB kv_store")
                return cfg
            except Exception:
                log.exception("legacy JSON config load failed; starting fresh")
        return AlertConfig()


async def save_config(cfg: AlertConfig) -> None:
    async with _lock:
        trade_store.set_kv(CONFIG_KEY, cfg.model_dump(mode="json"))


def _all_chat_ids(cfg: "AlertConfig") -> list[str]:
    """Merge legacy single-chat field with the new multi-chat list, deduped."""
    out: list[str] = []
    seen: set[str] = set()
    for cid in [cfg.chat_id, *cfg.chat_ids]:
        cid = (cid or "").strip()
        if cid and cid not in seen:
            seen.add(cid)
            out.append(cid)
    return out


async def broadcast_telegram(token: str, chat_ids: list[str], text: str) -> tuple[bool, str]:
    """Send `text` to every chat in parallel. Returns (any_succeeded, summary).
    'any_succeeded' is True if at least one delivery worked, so the caller can
    mark the signal as 'notified' without redelivering to recipients that
    already got it."""
    if not chat_ids:
        return False, "no chat_ids configured"
    results = await asyncio.gather(*[
        send_telegram(token, cid, text) for cid in chat_ids
    ], return_exceptions=False)
    failures = [(cid, err) for cid, (ok, err) in zip(chat_ids, results) if not ok]
    succeeded = sum(1 for ok, _ in results if ok)
    if failures:
        log.warning("broadcast partial: %d/%d delivered; failures: %s",
                    succeeded, len(chat_ids),
                    "; ".join(f"{cid}:{err}" for cid, err in failures))
    return succeeded > 0, f"{succeeded}/{len(chat_ids)} delivered"


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


def _format_closure(symbol: str, name: str, pending: PendingSignal, sig) -> str:
    """Message sent when a previously-notified open trade resolves."""
    safe_name = name.replace("*", "").replace("_", "\\_")
    if sig.status == "WIN":
        head = f"✅ *WIN* — `{symbol}` ({pending.side} @ ${pending.entry:,.2f})"
        exit_price = pending.target
        pnl_dir = "+"
    else:  # LOSS
        head = f"❌ *LOSS* — `{symbol}` ({pending.side} @ ${pending.entry:,.2f})"
        exit_price = pending.stop
        pnl_dir = "-"
    pnl_pct = abs(sig.pnl_pct or 0.0)
    return "\n".join([
        head,
        f"*Strategy:* {safe_name}",
        f"*Exit:* `${exit_price:,.2f}`",
        f"*P&L:* {pnl_dir}{pnl_pct:.2f}% (signal-level)",
    ])


async def _evaluate_subscription(sub: Subscription, symbol: str):
    """Returns (latest_open_signal_or_None, full_signals_list, strategy_name,
    resolved_interval, entry_tf_candles).

    `entry_tf_candles` are the candles that the strategy's signals are
    indexed on (5m for SMC MTF, 1h for other MTFs, the user's interval
    otherwise). The close-pass needs them so it can resolve DB-tracked
    open trades by building a synthetic Signal and running annotate, even
    when the strategy itself no longer re-emits at that bar (e.g. when
    rolling support/resistance levels shifted)."""
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
        entry_candles = c5
    elif is_mtf(sid):
        c1h, c4h, c1d = await asyncio.gather(
            fetch_klines(symbol, "1h", 1000),
            fetch_klines(symbol, "4h", 1000),
            fetch_klines(symbol, "1d", 1000),
        )
        ctx = MTFContext(candles_1h=c1h, candles_4h=c4h, candles_1d=c1d)
        signals = annotate(run_mtf(sid, ctx, start_idx=50), c1h)
        entry_candles = c1h
    else:
        strat = get_strategy(sid)
        candles = await fetch_klines(symbol, interval, 500)
        signals = annotate(strat.evaluate(candles), candles)
        entry_candles = candles

    open_signals = [s for s in signals if s.status == "OPEN"]
    return (open_signals[-1] if open_signals else None), signals, name, interval, entry_candles


def _utc_midnight(ts: int) -> int:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    midnight = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(midnight.timestamp())


async def _sync_position_state(at: AutoTradeConfig, symbol: str) -> None:
    """Detect natural OCO fills (stop or target hit by the market) by reading
    the actual BTC balance. If we recorded a LONG but the wallet has no base
    asset left, the bracket fired -- clear the local state so the next signal
    can act fresh."""
    if at.current_position is None:
        return
    if not at.api_key or not at.api_secret:
        return
    base_asset = symbol.replace("USDT", "").replace("BUSD", "").replace("USDC", "")
    try:
        bal = await get_balance(at.api_key, at.api_secret, base_asset)
    except Exception as e:
        log.warning("position sync failed: %s", e)
        return
    # Use 50% of recorded qty as threshold so partial fills don't fool us.
    if bal < at.current_position.qty * 0.5:
        log.info("[AUTO-TRADE] position cleared (balance %.6f < half of recorded %.6f)",
                 bal, at.current_position.qty)
        at.current_position = None


async def _close_position(at: AutoTradeConfig, symbol: str) -> tuple[bool, str]:
    """Cancel any open OCO brackets then market-close the current position.
    Returns (ok, message)."""
    pos = at.current_position
    if pos is None:
        return True, "no position to close"
    try:
        await cancel_all_open_orders(at.api_key, at.api_secret, symbol)
    except Exception as e:
        log.warning("[AUTO-TRADE] cancel-all before close failed: %s", e)
    close_side = "SELL" if pos.side == "LONG" else "BUY"
    try:
        await place_market(at.api_key, at.api_secret, symbol, close_side, pos.qty)
    except Exception as e:
        at.last_trade_error = f"close failed: {e}"
        return False, f"close failed: {e}"
    at.current_position = None
    return True, f"closed {pos.side} {pos.qty:.6f}"


async def _maybe_auto_execute(cfg: AlertConfig, sub: Subscription, sig) -> str | None:
    """Smart manager — handles position state to avoid averaging and to
    reverse cleanly on opposite signals.

    Spot rules (current code path):
      no position + BUY signal   -> open LONG
      no position + SELL signal  -> skip (Spot can't short)
      LONG       + BUY signal    -> skip (no averaging)
      LONG       + SELL signal   -> close LONG, leave flat

    Telegram message reflects whichever path was taken.
    """
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

    # First: clean up stale position state by checking the wallet
    await _sync_position_state(at, cfg.symbol)

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

    new_side = "LONG" if sig.type == "BUY" else "SHORT"
    pos = at.current_position

    # === Smart position management ===
    # Case 1: same direction as existing position -> NO AVERAGING
    if pos is not None and pos.side == new_side:
        return (f"auto-trade: skipped (already {pos.side} from "
                f"{pos.strategy_id}; no averaging)")

    # Case 2: opposite direction -> close existing first
    closed_msg = ""
    if pos is not None and pos.side != new_side:
        ok, msg = await _close_position(at, cfg.symbol)
        if not ok:
            return f"auto-trade: REVERSE-CLOSE FAILED — {msg}"
        closed_msg = f"closed prior {pos.side} ({pos.strategy_id}) ✂️ "
        # After closing, the next-step continues below to open the new direction.

    # Case 3: new signal direction
    # On Spot you cannot short -- a SELL signal with no LONG is a no-op.
    if new_side == "SHORT":
        return (f"{closed_msg}auto-trade: SELL signal with no LONG to close "
                "(Spot can't short).")

    # Sizing for the new entry
    risk = min(at.risk_pct, MAX_RISK_PCT)
    try:
        info = await get_exchange_info(cfg.symbol)
    except Exception as e:
        at.last_trade_error = f"exchange info failed: {e}"
        return f"{closed_msg}auto-trade: skipped (exchange info: {e})"

    qty, sizing_msg = compute_quantity(
        capital_usd=at.capital_usd, risk_pct=risk,
        entry=sig.entry, stop=sig.stop_loss,
        step_size=info["step_size"], min_qty=info["min_qty"],
        min_notional=info["min_notional"],
        max_position_usd=at.max_position_usd,
    )
    if qty <= 0:
        return f"{closed_msg}auto-trade: skipped ({sizing_msg})"

    # Place the entry market order (BUY for LONG)
    try:
        log.info("[AUTO-TRADE] placing BUY %s qty=%s (%s)",
                 cfg.symbol, qty, sizing_msg)
        entry_resp = await place_market(at.api_key, at.api_secret, cfg.symbol, "BUY", qty)
    except Exception as e:
        at.last_trade_error = f"entry failed: {e}"
        log.error("[AUTO-TRADE] entry failed: %s", e)
        return f"{closed_msg}auto-trade: ENTRY FAILED — {e}"

    # Place OCO bracket exit (SELL stop + SELL target)
    tick = info["tick_size"]
    stop_limit = sig.stop_loss - tick * 2  # below stop_price for BUY long exit
    try:
        await place_oco(
            at.api_key, at.api_secret, cfg.symbol, "SELL", qty,
            take_profit_price=sig.target,
            stop_price=sig.stop_loss,
            stop_limit_price=stop_limit,
        )
    except Exception as e:
        at.last_trade_error = f"OCO failed: {e}"
        log.error("[AUTO-TRADE] OCO failed — position is UNPROTECTED: %s", e)
        # Record the position anyway so manager doesn't try to open another
        at.current_position = OpenPosition(
            side="LONG", qty=qty, entry=sig.entry,
            stop=sig.stop_loss, target=sig.target,
            strategy_id=sub.strategy_id, opened_at=now,
        )
        at.trades_today += 1
        return (
            f"{closed_msg}⚠️ auto-trade: ENTRY FILLED but OCO failed ({e}). "
            "Position is UNPROTECTED. Place manual stop+target NOW."
        )

    # All good — store position
    at.current_position = OpenPosition(
        side="LONG", qty=qty, entry=sig.entry,
        stop=sig.stop_loss, target=sig.target,
        strategy_id=sub.strategy_id, opened_at=now,
    )
    at.trades_today += 1
    at.last_trade_error = ""
    fill_price = float(entry_resp.get("fills", [{}])[0].get("price", sig.entry))
    return (
        f"{closed_msg}✅ auto-trade: filled BUY {qty:.6f} @ ${fill_price:.2f} "
        f"(daily {at.trades_today}/{at.max_trades_per_day})"
    )


async def _global_resolve_pass() -> int:
    """Walk every OPEN row in the DB, fetch the (symbol, interval) candles
    once per combo, and resolve via annotate + synthetic Signal. This runs
    on every tick regardless of subscriptions or alert-enabled state, so a
    trade is never orphaned by the user unsubscribing from its strategy.

    Returns the number of rows newly closed."""
    rows = trade_store.all_open_trades()
    if not rows:
        return 0

    # Bucket by (symbol, interval) so we make at most one fetch_klines call
    # per market regardless of how many strategies have open trades there.
    by_combo: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        by_combo.setdefault((r["symbol"], r["interval"]), []).append(r)

    closed = 0
    for (symbol, interval), group in by_combo.items():
        try:
            candles = await fetch_klines(symbol, interval, 500)
        except Exception as e:
            log.warning("[RESOLVE] fetch_klines failed for %s/%s: %s", symbol, interval, e)
            continue
        for r in group:
            synth = Signal(
                time=r["signal_time"], type=r["type"], price=r["entry"],
                reason=r.get("reason") or "",
                entry=r["entry"], stop_loss=r["stop_loss"], target=r["target"],
            )
            resolved = annotate([synth], candles)[0]
            if resolved.status not in ("WIN", "LOSS"):
                continue
            exit_price = resolved.target if resolved.status == "WIN" else resolved.stop_loss
            ok = trade_store.close_trade(
                strategy_id=r["strategy_id"],
                interval=r["interval"],
                signal_time=r["signal_time"],
                status=resolved.status,
                exit_price=float(exit_price) if exit_price is not None else 0.0,
                exit_time=int(resolved.closed_at or 0),
                pnl_pct=float(resolved.pnl_pct or 0.0),
            )
            if ok:
                closed += 1
                log.info(
                    "[RESOLVE] %s %s @ %s on %s -> %s pnl=%.2f%%",
                    r["strategy_id"], r["type"], r["signal_time"], r["symbol"],
                    resolved.status, resolved.pnl_pct or 0.0,
                )
    return closed


async def alert_loop():
    """Background task, started from main.py on startup."""
    log.info("alert worker started; polling every %ss", POLL_SECONDS)
    while True:
        try:
            cfg = await load_config()

            # Always run the global resolve pass first. It does not need any
            # subscription or alert-enabled state -- if there is an OPEN row
            # in the DB and price has hit its stop or target, close it.
            try:
                await _global_resolve_pass()
            except Exception:
                log.exception("global resolve pass crashed; continuing")

            recipients = _all_chat_ids(cfg)
            watch_symbols = cfg.symbols or [cfg.symbol or DEFAULT_SYMBOL]
            if cfg.enabled and cfg.token and recipients and cfg.subscriptions:
                changed = False
                # Nested loop: every (symbol, subscription) gets evaluated.
                # Order is symbol-outer so all Telegram alerts for one coin
                # cluster together in chat -- easier for the reader.
                for symbol in watch_symbols:
                    for sub in cfg.subscriptions:
                        key = _state_key(symbol, sub.strategy_id)
                        try:
                            latest, all_signals, name, interval, entry_candles = \
                                await _evaluate_subscription(sub, symbol)
                        except Exception as e:
                            log.warning("eval %s/%s failed: %s", symbol, sub.strategy_id, e)
                            continue

                        # Per-(symbol, strategy) close pass on this tick's candles.
                        # The global resolve already covered the orphan case --
                        # this one stays so the latest fetched candles can resolve
                        # right after a new signal lands.
                        try:
                            for row in trade_store.open_trades(sub.strategy_id, interval, symbol):
                                synth = Signal(
                                    time=row["signal_time"], type=row["type"],
                                    price=row["entry"], reason=row.get("reason") or "",
                                    entry=row["entry"], stop_loss=row["stop_loss"],
                                    target=row["target"],
                                )
                                resolved = annotate([synth], entry_candles)[0]
                                if resolved.status not in ("WIN", "LOSS"):
                                    continue
                                exit_price = (
                                    resolved.target if resolved.status == "WIN"
                                    else resolved.stop_loss
                                )
                                trade_store.close_trade(
                                    strategy_id=sub.strategy_id, interval=interval,
                                    signal_time=row["signal_time"],
                                    status=resolved.status,
                                    exit_price=float(exit_price) if exit_price is not None else 0.0,
                                    exit_time=int(resolved.closed_at or 0),
                                    pnl_pct=float(resolved.pnl_pct or 0.0),
                                )
                                changed = True
                                log.info("[CLOSED] %s/%s %s @ %s -> %s pnl=%.2f%%",
                                         symbol, sub.strategy_id, row["type"], row["signal_time"],
                                         resolved.status, resolved.pnl_pct or 0.0)
                        except Exception:
                            log.exception("close pass failed for %s/%s", symbol, sub.strategy_id)

                        # Pending closure Telegram (per symbol).
                        pending = cfg.pending_close.get(key)
                        if pending is not None:
                            matching = next((s for s in all_signals if s.time == pending.time), None)
                            if matching is not None and matching.status in ("WIN", "LOSS"):
                                close_msg = _format_closure(symbol, name, pending, matching)
                                ok_c, _ = await broadcast_telegram(cfg.token, recipients, close_msg)
                                if ok_c:
                                    cfg.pending_close.pop(key, None)
                                    changed = True
                                    log.info("[CLOSURE] sent %s for %s/%s @ %s",
                                             matching.status, symbol, sub.strategy_id, matching.time)

                        if latest is None:
                            continue
                        last_seen = cfg.last_seen.get(key, 0)
                        if latest.time > last_seen:
                            log.info(
                                "[ALERT] %s/%s type=%s entry=%s stop=%s target=%s reason=%r",
                                symbol, sub.strategy_id, latest.type, latest.entry,
                                latest.stop_loss, latest.target, latest.reason,
                            )
                            eff_type, corrected = _verify_direction(latest)
                            if corrected:
                                log.error(
                                    "[DIRECTION-MISMATCH] %s/%s declared %s but geometry %s",
                                    symbol, sub.strategy_id, latest.type, eff_type,
                                )

                            # Auto-trade only fires on the dedicated auto-trade
                            # symbol; the rest are Telegram + DB only.
                            trade_status = None
                            if symbol == cfg.symbol:
                                trade_status = await _maybe_auto_execute(cfg, sub, latest)
                            msg = _format_signal(symbol, name, latest)
                            if trade_status:
                                msg = msg + "\n\n" + trade_status
                            ok, err = await broadcast_telegram(cfg.token, recipients, msg)
                            if ok:
                                cfg.last_seen[key] = latest.time
                                if (latest.entry is not None and latest.stop_loss is not None
                                        and latest.target is not None):
                                    cfg.pending_close[key] = PendingSignal(
                                        time=latest.time, side=latest.type,
                                        entry=latest.entry, stop=latest.stop_loss,
                                        target=latest.target,
                                    )
                                    try:
                                        trade_store.insert_trade(
                                            strategy_id=sub.strategy_id,
                                            interval=interval, symbol=symbol,
                                            signal_time=latest.time, type_=latest.type,
                                            entry=float(latest.entry),
                                            stop_loss=float(latest.stop_loss),
                                            target=float(latest.target),
                                            reason=str(latest.reason or ""),
                                            created_at=int(time.time()),
                                        )
                                    except Exception:
                                        log.exception("insert failed for %s/%s", symbol, sub.strategy_id)
                                changed = True
                                log.info("sent alert for %s/%s @ %s",
                                         symbol, sub.strategy_id, latest.time)
                            else:
                                cfg.last_error = f"{symbol}/{sub.strategy_id}: {err}"
                                changed = True
                                log.warning("send failed: %s", err)
                cfg.last_poll = int(time.time())
                if changed or cfg.last_poll - getattr(cfg, "last_poll", 0) > 60:
                    await save_config(cfg)
        except Exception:
            log.exception("alert_loop tick crashed; will retry")
        await asyncio.sleep(POLL_SECONDS)
