"""Market outlook endpoint — structured 'what to watch next session' data.

Same logic as scripts/market_outlook.py but returns JSON. The frontend uses
this to render a 'Trade Plan' card above the strategy panel.
"""
import asyncio

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..binance import fetch_klines
from ..indicators import adx, atr, bollinger, ema, rsi
from ..multi_tf import MTFContext

router = APIRouter(prefix="/api/outlook", tags=["outlook"])


class CurrentInfo(BaseModel):
    price: float
    today_open: float
    today_high: float
    today_low: float
    today_change_pct: float
    yesterday_close: float
    yesterday_change_pct: float


class RegimeInfo(BaseModel):
    daily: str
    daily_adx: float
    h4: str
    ema50_d: float
    ema200_d: float


class LevelsInfo(BaseModel):
    swing_high_20d: float
    swing_low_20d: float
    bb_upper: float
    bb_middle: float
    bb_lower: float
    ema20_d: float
    rsi_d: float
    rsi_label: str


class VolatilityInfo(BaseModel):
    daily_atr: float
    expected_low: float
    expected_high: float
    expected_pct: float


class TradePlan(BaseModel):
    bias: str  # 'LONG', 'SHORT', 'NEUTRAL'
    summary: str
    long_trigger: str
    long_entry_zone: float
    long_stop: float
    long_target: float
    short_trigger: str
    short_entry_zone: float
    short_stop: float
    short_target: float
    regime_change_bull: float
    regime_change_bear: float


class OutlookResponse(BaseModel):
    symbol: str
    generated_at: int
    current: CurrentInfo
    regime: RegimeInfo
    levels: LevelsInfo
    volatility: VolatilityInfo
    plan: TradePlan


@router.get("", response_model=OutlookResponse)
async def get_outlook(symbol: str = Query("BTCUSDT")):
    try:
        c1h, c4h, c1d = await asyncio.gather(
            fetch_klines(symbol, "1h", 300),
            fetch_klines(symbol, "4h", 500),
            fetch_klines(symbol, "1d", 500),
        )
    except Exception as e:
        raise HTTPException(502, f"Binance error: {e}")

    last = c1h[-1]
    today_d = c1d[-1]
    yest_d = c1d[-2]

    ctx = MTFContext(candles_1h=c1h, candles_4h=c4h, candles_1d=c1d)
    d_regime = ctx.daily_regime_at(last.time, adx_min=20.0)
    h4_regime = ctx.h4_regime_at(last.time)

    closes_d = [c.close for c in c1d]
    highs_d = [c.high for c in c1d]
    lows_d = [c.low for c in c1d]
    d_e20 = ema(closes_d, 20)[-1]
    d_e50 = ema(closes_d, 50)[-1]
    d_e200 = ema(closes_d, 200)[-1]
    d_adx, _, _ = adx(highs_d, lows_d, closes_d, 14)
    d_atr = atr(highs_d, lows_d, closes_d, 14)[-1]
    d_rsi = rsi(closes_d, 14)[-1]
    bbu, bbm, bbl = bollinger(closes_d, 20, 2.0)
    bbu, bbm, bbl = bbu[-1], bbm[-1], bbl[-1]
    swing_high = max(c.high for c in c1d[-20:])
    swing_low = min(c.low for c in c1d[-20:])

    rsi_label = "oversold" if d_rsi < 30 else "overbought" if d_rsi > 70 else "neutral"

    today_chg = (today_d.close - today_d.open) / today_d.open * 100.0
    yest_chg = (yest_d.close - yest_d.open) / yest_d.open * 100.0

    # Build trade plan based on regime
    if d_regime == "BULL":
        bias = "LONG"
        summary = "Daily uptrend confirmed by ADX. Buy pullbacks; avoid shorts."
        long_trigger = "Pullback to EMA20 or 1h RSI bounce from <40"
        long_entry_zone = d_e20
        long_stop = d_e20 - d_atr * 1.5
        long_target = swing_high
        short_trigger = "Counter-trend; only at major resistance"
        short_entry_zone = swing_high
        short_stop = swing_high + d_atr * 0.5
        short_target = d_e50
    elif d_regime == "BEAR":
        bias = "SHORT"
        summary = "Daily downtrend confirmed by ADX. Sell rallies; avoid longs."
        short_trigger = "Bounce to EMA20 or 1h RSI rejection from >60"
        short_entry_zone = d_e20
        short_stop = d_e20 + d_atr * 1.5
        short_target = swing_low
        long_trigger = "Counter-trend; only at major support"
        long_entry_zone = swing_low
        long_stop = swing_low - d_atr * 0.5
        long_target = d_e50
    else:  # CHOP
        bias = "NEUTRAL"
        summary = (
            f"Daily is in CHOP (ADX={d_adx[-1]:.1f}). Range-trade key levels; "
            "do NOT chase moves from the middle of the range."
        )
        long_trigger = "Price near BB lower AND 1h RSI < 30"
        long_entry_zone = bbl
        long_stop = bbl * 0.99
        long_target = bbm
        short_trigger = "Price near BB upper AND 1h RSI > 70"
        short_entry_zone = bbu
        short_stop = bbu * 1.01
        short_target = bbm

    return OutlookResponse(
        symbol=symbol.upper(),
        generated_at=last.time,
        current=CurrentInfo(
            price=last.close,
            today_open=today_d.open, today_high=today_d.high, today_low=today_d.low,
            today_change_pct=today_chg,
            yesterday_close=yest_d.close, yesterday_change_pct=yest_chg,
        ),
        regime=RegimeInfo(
            daily=d_regime, daily_adx=d_adx[-1], h4=h4_regime,
            ema50_d=d_e50, ema200_d=d_e200,
        ),
        levels=LevelsInfo(
            swing_high_20d=swing_high, swing_low_20d=swing_low,
            bb_upper=bbu, bb_middle=bbm, bb_lower=bbl,
            ema20_d=d_e20, rsi_d=d_rsi, rsi_label=rsi_label,
        ),
        volatility=VolatilityInfo(
            daily_atr=d_atr,
            expected_low=last.close - d_atr,
            expected_high=last.close + d_atr,
            expected_pct=d_atr / last.close * 100.0,
        ),
        plan=TradePlan(
            bias=bias, summary=summary,
            long_trigger=long_trigger, long_entry_zone=long_entry_zone,
            long_stop=long_stop, long_target=long_target,
            short_trigger=short_trigger, short_entry_zone=short_entry_zone,
            short_stop=short_stop, short_target=short_target,
            regime_change_bull=swing_high, regime_change_bear=swing_low,
        ),
    )
