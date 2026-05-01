"""Multi-timeframe SMC engine: 5m execution + 15m structure + 1h trend.

This is the proper top-down ICT/SMC methodology:
  1. 1h gives the directional bias (trade with the trend, never against)
  2. 15m gives the high-probability zones (FVG, Order Block)
  3. 5m gives the precise entry trigger (impulse + reversal candle)

Bar alignment is strict — at any 5m bar at time t, we only look at 15m and
1h bars that have CLOSED before t. This prevents lookahead bias.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass

from .indicators import adx, atr, ema, rsi
from .schemas import Candle, Signal
from .smc import (
    detect_liquidity_sweep,
    detect_recent_unfilled_fvg,
    find_recent_order_block,
    in_killzone,
    premium_discount,
    structure_bias,
)


# Tuning constants exposed for easy adjustment.
MIN_MOMENTUM = 400.0
MOMENTUM_BARS = 6
ADX_MIN_1H = 15.0           # ADX threshold on 1h — must be at least mild trend
RSI_BULL_PULLBACK = 45.0    # buy when 5m RSI was below this and turning up
RSI_BEAR_PULLBACK = 55.0
ATR_MULT = 1.5
STOP_PCT_MIN = 0.003
STOP_PCT_MAX = 0.012
REWARD_R = 2.0
COOLDOWN_BARS_5M = 6


@dataclass
class SMCMTFContext:
    candles_5m: list[Candle]
    candles_15m: list[Candle]
    candles_1h: list[Candle]

    def __post_init__(self):
        # 1h trend indicators
        c = [k.close for k in self.candles_1h]
        h = [k.high for k in self.candles_1h]
        l = [k.low for k in self.candles_1h]
        self.h1_ema50 = ema(c, 50)
        self.h1_ema200 = ema(c, 200)
        self.h1_adx, _, _ = adx(h, l, c, 14)
        self.h1_times = [k.time for k in self.candles_1h]

        # 15m structure indicators
        self.h15_times = [k.time for k in self.candles_15m]

        # 5m execution indicators
        c5 = [k.close for k in self.candles_5m]
        h5 = [k.high for k in self.candles_5m]
        l5 = [k.low for k in self.candles_5m]
        self.h5_ema20 = ema(c5, 20)
        self.h5_atr = atr(h5, l5, c5, 14)
        self.h5_rsi = rsi(c5, 14)

    # ---- alignment helpers ----
    def _last_closed(self, times: list[int], t: int, interval_sec: int) -> int:
        """Index of the latest bar in `times` that has fully closed by time t."""
        cutoff = t - interval_sec
        return bisect_right(times, cutoff) - 1

    def trend_bias_at(self, t: int) -> str:
        """Returns 'BULL', 'BEAR', or 'NONE' based on 1h regime.

        Uses price vs EMA50 as the bias (works in mild trends and strong ones).
        ADX must be at least mild to ensure *some* trend exists -- the 1h is
        just for direction; the 15m/5m do the heavy filtering.
        """
        idx = self._last_closed(self.h1_times, t, 3600)
        if idx < 0:
            return "NONE"
        e50, adx_v = self.h1_ema50[idx], self.h1_adx[idx]
        if None in (e50, adx_v):
            return "NONE"
        if adx_v < ADX_MIN_1H:
            return "NONE"  # mostly chop -- no bias
        last_close = self.candles_1h[idx].close
        if last_close > e50:
            return "BULL"
        if last_close < e50:
            return "BEAR"
        return "NONE"

    def h15_idx_for(self, t: int) -> int:
        """Index of the 15m bar that has closed by time t."""
        return self._last_closed(self.h15_times, t, 900)


def evaluate_smc_mtf(ctx: SMCMTFContext, start_idx: int = 0) -> list[Signal]:
    """Walk the 5m candles top-down: 1h trend → 15m zones → 5m trigger."""
    out: list[Signal] = []
    last_sig_idx = -10**9

    for i in range(max(60, start_idx), len(ctx.candles_5m)):
        if i - last_sig_idx < COOLDOWN_BARS_5M:
            continue

        c = ctx.candles_5m[i]
        atr_v = ctx.h5_atr[i]
        e20 = ctx.h5_ema20[i]
        rsi_v, rsi_p = ctx.h5_rsi[i], ctx.h5_rsi[i - 1]
        if None in (atr_v, e20, rsi_v, rsi_p):
            continue

        # 0. Killzone filter — only trade during London / NY sessions
        if not in_killzone(c.time):
            continue

        # 1. 1h trend bias
        bias = ctx.trend_bias_at(c.time)
        if bias == "NONE":
            continue
        direction = "bullish" if bias == "BULL" else "bearish"

        # 2. 15m timeframe context
        h15_idx = ctx.h15_idx_for(c.time)
        if h15_idx < 40:  # need at least 2 * structure lookback (20)
            continue

        # 1b. 15m market structure must NOT contradict 1h bias.
        # NONE is acceptable (mid-trend consolidation); only reject opposite structure.
        struct = structure_bias(ctx.candles_15m, h15_idx, lookback=20)
        if (bias == "BULL" and struct == "BEAR") or (bias == "BEAR" and struct == "BULL"):
            continue

        # 1c. Premium/Discount filter — buy only in discount, sell only in premium.
        # The "value" check: don't chase. Use 15m for the leg reference.
        zone = premium_discount(ctx.candles_15m, h15_idx, lookback=30)
        if bias == "BULL" and zone == "premium":
            continue   # don't buy at the high
        if bias == "BEAR" and zone == "discount":
            continue   # don't sell at the low

        # 2b. 15m structure: where would smart money buy/sell?
        # Note: a 15m FVG/OB existing already implies past momentum (the
        # impulse that created the gap). No need for a separate 5m
        # momentum check -- that would contradict "wait for the retest".

        # The momentum that created the 15m structure should be >= 400 pts.
        # We capture this by requiring `min_move` on the OB scan below.
        win15 = ctx.candles_15m[max(0, h15_idx - MOMENTUM_BARS): h15_idx + 1]
        h15_momentum = max(k.high for k in win15) - min(k.low for k in win15)
        if h15_momentum < MIN_MOMENTUM:
            continue

        h15_fvg = detect_recent_unfilled_fvg(ctx.candles_15m, h15_idx, direction, lookback=15)
        h15_ob = find_recent_order_block(
            ctx.candles_15m, h15_idx, direction,
            scan_back=10, lookahead=4, min_move=MIN_MOMENTUM,
        )

        # 4. Did the 5m bar tap a 15m zone and hold?
        confluences: list[str] = []
        in_zone = False

        if h15_fvg is not None:
            if direction == "bullish" and c.low <= h15_fvg["top"] and c.close > h15_fvg["bottom"]:
                confluences.append(f"15m FVG retest {h15_fvg['bottom']:.0f}-{h15_fvg['top']:.0f}")
                in_zone = True
            elif direction == "bearish" and c.high >= h15_fvg["bottom"] and c.close < h15_fvg["top"]:
                confluences.append(f"15m FVG retest {h15_fvg['top']:.0f}-{h15_fvg['bottom']:.0f}")
                in_zone = True

        if h15_ob is not None:
            if direction == "bullish" and c.low <= h15_ob["top"] and c.close > h15_ob["bottom"]:
                confluences.append(f"15m OB retest {h15_ob['bottom']:.0f}-{h15_ob['top']:.0f}")
                in_zone = True
            elif direction == "bearish" and c.high >= h15_ob["bottom"] and c.close < h15_ob["top"]:
                confluences.append(f"15m OB retest {h15_ob['top']:.0f}-{h15_ob['bottom']:.0f}")
                in_zone = True

        if not in_zone:
            continue

        # 5. 5m entry trigger — RSI reversal or liquidity sweep
        rsi_trigger = False
        if direction == "bullish" and rsi_p < RSI_BULL_PULLBACK and rsi_v > rsi_p:
            rsi_trigger = True
            confluences.append(f"5m RSI bounce ({rsi_p:.0f}->{rsi_v:.0f})")
        elif direction == "bearish" and rsi_p > RSI_BEAR_PULLBACK and rsi_v < rsi_p:
            rsi_trigger = True
            confluences.append(f"5m RSI roll ({rsi_p:.0f}->{rsi_v:.0f})")

        sweep = detect_liquidity_sweep(ctx.candles_5m, i, lookback=20)
        sweep_trigger = False
        if sweep is not None:
            if direction == "bullish" and sweep["type"] == "bullish_sweep":
                confluences.append(f"5m liq sweep @{sweep['level']:.0f}")
                sweep_trigger = True
            if direction == "bearish" and sweep["type"] == "bearish_sweep":
                confluences.append(f"5m liq sweep @{sweep['level']:.0f}")
                sweep_trigger = True

        if not (rsi_trigger or sweep_trigger):
            continue  # no entry trigger

        # 6. Risk management
        stop_dist = atr_v * ATR_MULT
        stop_dist = max(stop_dist, c.close * STOP_PCT_MIN)
        stop_dist = min(stop_dist, c.close * STOP_PCT_MAX)
        target_dist = stop_dist * REWARD_R

        if bias == "BULL":
            stop = c.close - stop_dist
            target = c.close + target_dist
            out.append(Signal(
                time=c.time, type="BUY", price=c.close,
                reason=(
                    f"SMC MTF (1h BULL, 15m {struct} {zone}): "
                    f"{h15_momentum:.0f}pt impulse + "
                    + " + ".join(confluences)
                ),
                entry=c.close, stop_loss=stop, target=target,
            ))
            last_sig_idx = i
        else:
            stop = c.close + stop_dist
            target = c.close - target_dist
            out.append(Signal(
                time=c.time, type="SELL", price=c.close,
                reason=(
                    f"SMC MTF (1h BEAR, 15m {struct} {zone}): "
                    f"{h15_momentum:.0f}pt impulse + "
                    + " + ".join(confluences)
                ),
                entry=c.close, stop_loss=stop, target=target,
            ))
            last_sig_idx = i

    return out
