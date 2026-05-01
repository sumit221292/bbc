"""SMC + Momentum strategy — designed for 5m and 15m BTCUSDT timeframes.

The user's brief:
  - Minimum momentum: 400 points (BTC dollar move) within last few bars
  - Use Order Block, Liquidity, FVG, Support/Resistance
  - Plus other useful tools as needed for profitability

Confluence model — every signal must satisfy:
  1) Trend bias matches (EMA20 vs EMA50 on the chart timeframe)
  2) 400-point impulse exists in the last 6 bars (the "momentum filter")
  3) AT LEAST ONE Smart-Money concept aligns: FVG retest, Order Block retest,
     or Liquidity sweep + reclaim
  4) Risk:reward stays at 2R via ATR-sized stops, capped to a sane percentage

This is intentionally selective. On a quiet market it will fire only a
handful of times a day — that's the design, not a bug.
"""
from __future__ import annotations

from ..indicators import atr, ema
from ..schemas import Candle, Signal
from ..smc import (
    detect_liquidity_sweep,
    detect_recent_unfilled_fvg,
    find_recent_order_block,
)
from .base import Strategy


class SMCMomentum(Strategy):
    id = "smc_momentum"
    name = "SMC + Momentum (5m / 15m)"
    description = (
        "Smart Money Concepts: 400-point impulse + at least one of "
        "(FVG retest / Order Block retest / Liquidity sweep). Trend-filtered "
        "by EMA20/EMA50. Designed for 5m and 15m BTC charts -- chart "
        "auto-switches to 15m when this is selected."
    )

    # --- momentum filter ---
    MIN_MOMENTUM = 400.0      # absolute USD move (BTC-tuned)
    MOMENTUM_BARS = 6         # within last 6 bars

    # --- trend ---
    EMA_SHORT = 20
    EMA_LONG = 50

    # --- SMC scan windows ---
    FVG_LOOKBACK = 15
    OB_SCAN_BACK = 12
    OB_LOOKAHEAD = 5
    SWEEP_LOOKBACK = 20

    # --- risk ---
    ATR_PERIOD = 14
    ATR_MULT = 1.5
    STOP_PCT_MIN = 0.003   # 0.3% min — short TFs need tight stops
    STOP_PCT_MAX = 0.012   # 1.2% max
    REWARD_R = 2.0
    COOLDOWN_BARS = 8

    def evaluate(self, candles: list[Candle]) -> list[Signal]:
        if len(candles) < 80:
            return []
        closes = self.closes(candles)
        e20 = ema(closes, self.EMA_SHORT)
        e50 = ema(closes, self.EMA_LONG)
        atrs = atr(self.highs(candles), self.lows(candles), closes, self.ATR_PERIOD)

        out: list[Signal] = []
        last_sig_idx = -10**9

        for i in range(60, len(candles)):
            if i - last_sig_idx < self.COOLDOWN_BARS:
                continue
            if e20[i] is None or e50[i] is None or atrs[i] is None:
                continue

            c = candles[i]
            uptrend = e20[i] > e50[i] and c.close > e20[i]
            downtrend = e20[i] < e50[i] and c.close < e20[i]
            if not (uptrend or downtrend):
                continue
            direction = "bullish" if uptrend else "bearish"

            # 1. Momentum filter — 400+ point move in last 6 bars
            window = candles[i - self.MOMENTUM_BARS: i + 1]
            high6 = max(k.high for k in window)
            low6 = min(k.low for k in window)
            momentum = high6 - low6
            if momentum < self.MIN_MOMENTUM:
                continue

            # The impulse direction must agree with the trend (last bar > first bar for longs)
            first_close = window[0].close
            if uptrend and c.close <= first_close:
                continue
            if downtrend and c.close >= first_close:
                continue

            # 2. SMC confluence — need >= 1
            confluences: list[str] = []

            fvg = detect_recent_unfilled_fvg(candles, i, direction, lookback=self.FVG_LOOKBACK)
            if fvg is not None:
                # current bar must be retesting the FVG zone (touched it AND held)
                if uptrend and c.low <= fvg["top"] and c.close > fvg["bottom"]:
                    confluences.append(f"FVG retest {fvg['bottom']:.0f}-{fvg['top']:.0f}")
                elif downtrend and c.high >= fvg["bottom"] and c.close < fvg["top"]:
                    confluences.append(f"FVG retest {fvg['top']:.0f}-{fvg['bottom']:.0f}")

            sweep = detect_liquidity_sweep(candles, i, lookback=self.SWEEP_LOOKBACK)
            if sweep is not None:
                if uptrend and sweep["type"] == "bullish_sweep":
                    confluences.append(f"liq sweep @{sweep['level']:.0f}")
                if downtrend and sweep["type"] == "bearish_sweep":
                    confluences.append(f"liq sweep @{sweep['level']:.0f}")

            ob = find_recent_order_block(
                candles, i, direction,
                scan_back=self.OB_SCAN_BACK,
                lookahead=self.OB_LOOKAHEAD,
                min_move=self.MIN_MOMENTUM,
            )
            if ob is not None:
                # Did current bar tap the OB zone?
                if uptrend and c.low <= ob["top"] and c.close > ob["bottom"]:
                    confluences.append(f"OB retest {ob['bottom']:.0f}-{ob['top']:.0f}")
                elif downtrend and c.high >= ob["bottom"] and c.close < ob["top"]:
                    confluences.append(f"OB retest {ob['top']:.0f}-{ob['bottom']:.0f}")

            if not confluences:
                continue

            # 3. Risk management
            atr_v = atrs[i]
            stop_dist = atr_v * self.ATR_MULT
            stop_dist = max(stop_dist, c.close * self.STOP_PCT_MIN)
            stop_dist = min(stop_dist, c.close * self.STOP_PCT_MAX)
            target_dist = stop_dist * self.REWARD_R

            if uptrend:
                stop = c.close - stop_dist
                target = c.close + target_dist
                out.append(Signal(
                    time=c.time, type="BUY", price=c.close,
                    reason=(
                        f"SMC bullish: {momentum:.0f}pt impulse + "
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
                        f"SMC bearish: {momentum:.0f}pt impulse + "
                        + " + ".join(confluences)
                    ),
                    entry=c.close, stop_loss=stop, target=target,
                ))
                last_sig_idx = i

        return out
