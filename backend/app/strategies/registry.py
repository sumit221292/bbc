"""Auto-registers strategies. To add a new one, just import the class here.

The registry is intentionally a plain dict — no decorators, no metaclass magic.
That keeps the strategy classes trivially testable in isolation.
"""
from .base import Strategy
from .best import BestTrade
from .scalping import ScalpingRSI
from .day_trading import DayTradingEMACross
from .swing import SwingSRBounce
from .trend_following import TrendFollowing
from .breakout import Breakout
from .macd_cross import MACDCross
from .bollinger_rev import BollingerReversion
from .supertrend_flip import SuperTrendFlip
from .donchian_turtle import DonchianTurtle
from .ichimoku_cross import IchimokuCross
from .stochastic_rev import StochasticReversal
from .adx_trend import ADXTrend
from .smc_momentum import SMCMomentum


# 'best' is intentionally first so the UI defaults to it.
_STRATEGIES: dict[str, type[Strategy]] = {
    cls.id: cls for cls in (
        BestTrade, SMCMomentum,
        ScalpingRSI, DayTradingEMACross, SwingSRBounce, TrendFollowing, Breakout,
        MACDCross, BollingerReversion, SuperTrendFlip, DonchianTurtle,
        IchimokuCross, StochasticReversal, ADXTrend,
    )
}


def get_strategy(strategy_id: str) -> Strategy:
    cls = _STRATEGIES.get(strategy_id)
    if cls is None:
        raise KeyError(strategy_id)
    return cls()


def list_strategies() -> list[type[Strategy]]:
    return list(_STRATEGIES.values())
