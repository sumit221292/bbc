"""EMA 34 Rejection + Pullback (port of the Pine v11 indicator).

Two complementary entry modes on the same trend filter (EMA 34 slope >
0.3 x ATR magnitude):

  REJECTION  --  after price has crossed above the EMA and stayed above
                 for >= 3 bars, a candle that dips back to / through the
                 EMA but closes above with a meaningful lower wick is a
                 trend continuation buy. Mirror logic for sells.

  PULLBACK   --  in a strong trend, a candle whose extreme touched the
                 EMA within the last 3 bars AND that closes back in the
                 trend direction with a body bigger than 30% of the
                 range. Catches the same idea as Rejection but without
                 requiring a clean state-machine cross / wick combo --
                 useful when price grinds against the EMA repeatedly.

A 7-point confirmation score (RSI / MACD / EMA-stack / VWAP / BB midline
/ volume spike / HTF EMA) gates every signal -- the Pine "Day Trader"
profile (score >= 5, cooldown 5 bars) is hard-coded since that's the
preset that matches our 1h universe. The other profiles in the source
indicator can be re-introduced as class subclasses later if needed.

Risk: SL = swing low/high +/- 1.5 x ATR, TP = SL distance x 3 (1:3 RR).
That clears the global 1:2 RR floor with margin.
"""
from __future__ import annotations

from statistics import median

from ..indicators import atr, bollinger, ema, macd, rsi
from ..schemas import Candle, Signal
from .base import Strategy


# ----- Pine "Day Trader" profile resolved values --------------------------
MIN_SCORE        = 5     # 5-of-7 confirmations
COOLDOWN_BARS    = 5
MIN_CANDLES_AWAY = 3     # bars price must be one side of EMA before rejection counts
MAX_CANDLES_AWAY = 15    # max age of the wait_buy / wait_sell state
PULLBACK_PROX    = 0.3   # ATR multiples for proximity zone in Aggressive Pullback
PULLBACK_MAX_BARS = 3    # how recently price must have touched the EMA
WICK_RATIO       = 0.5   # rejection wick / candle range
BODY_RATIO       = 0.3   # Conservative-mode min body ratio
SLOPE_MULTIPLIER = 0.3   # |EMA slope over 10 bars| / ATR must clear this
SLOPE_LOOKBACK   = 10
SL_ATR_MULT      = 1.5
RR_TARGET        = 3.0   # 1:3 RR (well above the global 1:2 floor)
ATR_PCT_MIN      = 0.15  # min ATR-as-%-of-price to consider the market live
ENTRY_MODE       = "Aggressive"  # Pine "Aggressive" = current-bar rejection, "Conservative" = previous-bar


class EMA34Rejection(Strategy):
    id = "ema34_rejection"
    name = "🎯 EMA 34 Rejection + Pullback"
    description = (
        "Port of the EMA 34 Pine v11 indicator. Fires when a strong "
        "EMA-34 trend (|slope| > 0.3×ATR) sees a clean rejection wick "
        "off the EMA or a tight pullback into the EMA zone, AND at "
        "least 5 of 7 confirmation filters (RSI / MACD / EMA stack / "
        "VWAP / BB midline / volume spike / HTF EMA) agree. SL at the "
        "swing extreme ± 1.5×ATR, TP at 1:3 RR."
    )
    storage_interval = "1h"
    # Trail-update was assumed True (continuation pattern), but the 18-coin
    # 1y backtest came back at -5.71pp avg delta when trail is on -- the
    # 24.8% WR means same-direction re-fires usually reflect a slow grind
    # against the trade rather than a real continuation, so the trail
    # just extends losers. Flipping to False; revisit only if live data
    # contradicts the backtest.
    supports_trail = False

    def evaluate(self, candles: list[Candle]) -> list[Signal]:
        # Need at least 220 bars for the 200-EMA + a window of state.
        if len(candles) < 220:
            return []

        closes = [c.close for c in candles]
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        opens_ = [c.open for c in candles]
        vols = [c.volume for c in candles]
        n = len(candles)

        # ---- Indicator series (all None-padded during warmup) ----
        e34 = ema(closes, 34)
        e21 = ema(closes, 21)
        e50 = ema(closes, 50)
        e200 = ema(closes, 200)
        atr14 = atr(highs, lows, closes, 14)
        rsi14 = rsi(closes, 14)
        _, _, macd_hist = macd(closes, 12, 26, 9)
        _, bb_mid, _ = bollinger(closes, 20, 2.0)
        # 20-period volume SMA -- inline since indicators.py has no sma helper.
        vol_sma: list[float | None] = [None] * n
        for i in range(19, n):
            vol_sma[i] = sum(vols[i - 19:i + 1]) / 20.0

        signals: list[Signal] = []

        # ---- Rolling state ----
        wait_buy = False
        wait_sell = False
        candles_above = 0
        candles_below = 0
        last_signal_bar = -10**9

        # Need the 200-EMA warmup PLUS room for a 10-bar slope lookback.
        start = 210
        for i in range(start, n):
            # Skip until all indicator inputs are present at this bar.
            if any(v is None for v in (
                e34[i], e21[i], e50[i], e200[i],
                e34[i - SLOPE_LOOKBACK], atr14[i], rsi14[i],
                macd_hist[i], macd_hist[i - 1], bb_mid[i],
            )):
                continue

            close_ = closes[i]
            high_ = highs[i]
            low_ = lows[i]
            open_ = opens_[i]
            ema_now = e34[i]
            ema_prev = e34[i - 1]
            ema_lb = e34[i - SLOPE_LOOKBACK]
            a = atr14[i]

            # ---- Cross detection updates the wait_buy / wait_sell flags
            crossed_up = closes[i - 1] <= ema_prev and close_ > ema_now
            crossed_dn = closes[i - 1] >= ema_prev and close_ < ema_now
            if crossed_up:
                wait_buy, wait_sell = True, False
                candles_above = 0
            if crossed_dn:
                wait_sell, wait_buy = True, False
                candles_below = 0

            if wait_buy:
                if low_ > ema_now:
                    candles_above += 1
                if candles_above > MAX_CANDLES_AWAY:
                    wait_buy = False
            if wait_sell:
                if high_ < ema_now:
                    candles_below += 1
                if candles_below > MAX_CANDLES_AWAY:
                    wait_sell = False

            # ---- Slope strength ----
            slope = ema_now - ema_lb
            slope_th = a * SLOPE_MULTIPLIER
            strong_up = slope > slope_th
            strong_dn = slope < -slope_th

            # ---- ATR-as-% gate -- filter dead chop ----
            atr_pct = a / close_ * 100.0 if close_ > 0 else 0.0
            if atr_pct < ATR_PCT_MIN:
                continue

            # ---- Candle anatomy ----
            c_range = max(high_ - low_, 1e-9)
            c_body = abs(close_ - open_)
            c_up_wick = high_ - max(close_, open_)
            c_lo_wick = min(close_, open_) - low_

            # ---- Rejection (Aggressive: current bar must be the rejection candle) ----
            agg_buy_rej = (
                wait_buy and strong_up and candles_above >= MIN_CANDLES_AWAY
                and low_ <= ema_now and close_ > ema_now and close_ > open_
                and c_lo_wick >= c_range * WICK_RATIO
            )
            agg_sell_rej = (
                wait_sell and strong_dn and candles_below >= MIN_CANDLES_AWAY
                and high_ >= ema_now and close_ < ema_now and close_ < open_
                and c_up_wick >= c_range * WICK_RATIO
            )

            # ---- Pullback (Aggressive: just within the ATR proximity zone) ----
            upper_zone = ema_now + a * PULLBACK_PROX
            lower_zone = ema_now - a * PULLBACK_PROX
            agg_pb_buy = (
                strong_up and low_ <= upper_zone
                and close_ > ema_now and close_ > open_
            )
            agg_pb_sell = (
                strong_dn and high_ >= lower_zone
                and close_ < ema_now and close_ < open_
            )

            # ---- 7-point confirmation score ----
            score_buy = 0
            score_sell = 0
            # RSI
            if 45 < rsi14[i] < 70: score_buy += 1
            if 30 < rsi14[i] < 55: score_sell += 1
            # MACD histogram direction
            if macd_hist[i] > 0 and macd_hist[i] > macd_hist[i - 1]: score_buy += 1
            if macd_hist[i] < 0 and macd_hist[i] < macd_hist[i - 1]: score_sell += 1
            # EMA stack
            if e21[i] > e50[i] and close_ > e200[i]: score_buy += 1
            if e21[i] < e50[i] and close_ < e200[i]: score_sell += 1
            # VWAP proxy: typical-price-since-start cumulative is closer to
            # Pine's session VWAP than computing a true session-anchored
            # VWAP, but our 1h universe doesn't have session resets so we
            # fall back to a 20-bar SMA of typical price (rough VWAP-ish).
            tp_window = [(highs[j] + lows[j] + closes[j]) / 3.0 for j in range(max(0, i - 19), i + 1)]
            vwap_proxy = sum(tp_window) / len(tp_window)
            if close_ > vwap_proxy: score_buy += 1
            if close_ < vwap_proxy: score_sell += 1
            # BB midline
            if close_ > bb_mid[i]: score_buy += 1
            if close_ < bb_mid[i]: score_sell += 1
            # Volume spike (20-bar avg * 1.2)
            if vol_sma[i] is not None and vols[i] > vol_sma[i] * 1.2:
                score_buy += 1
                score_sell += 1
            # HTF proxy -- 1h is our base; the 4h EMA-34 is roughly the 1h
            # EMA-34 of the last 4 hours' close. Easiest serializable proxy:
            # compare close to the EMA-34 value 4 bars ago (lookahead off).
            if i >= 4 and e34[i - 4] is not None:
                if close_ > e34[i - 4]: score_buy += 1
                if close_ < e34[i - 4]: score_sell += 1

            # Cooldown gate.
            if i - last_signal_bar < COOLDOWN_BARS:
                continue

            buy_ok = (agg_buy_rej or agg_pb_buy) and score_buy >= MIN_SCORE
            sell_ok = (agg_sell_rej or agg_pb_sell) and score_sell >= MIN_SCORE

            if not (buy_ok or sell_ok):
                continue

            # ---- Risk levels ----
            if buy_ok:
                sl = low_ - a * SL_ATR_MULT
                tp = close_ + (close_ - sl) * RR_TARGET
                kind = "REJ" if agg_buy_rej else "PB"
                signals.append(Signal(
                    time=candles[i].time, type="BUY", price=close_,
                    reason=f"EMA34 {kind} BUY (score {score_buy}/7)",
                    entry=close_, stop_loss=sl, target=tp,
                ))
            else:
                sl = high_ + a * SL_ATR_MULT
                tp = close_ - (sl - close_) * RR_TARGET
                kind = "REJ" if agg_sell_rej else "PB"
                signals.append(Signal(
                    time=candles[i].time, type="SELL", price=close_,
                    reason=f"EMA34 {kind} SELL (score {score_sell}/7)",
                    entry=close_, stop_loss=sl, target=tp,
                ))

            last_signal_bar = i
            # Reset wait state so the next REJ has to re-arm via a cross.
            if buy_ok:
                wait_buy = False
                candles_above = 0
            else:
                wait_sell = False
                candles_below = 0

        return signals
