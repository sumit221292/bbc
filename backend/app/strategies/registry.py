"""Auto-registers strategies. To add a new one, just import the class here.

The registry is intentionally a plain dict — no decorators, no metaclass magic.
That keeps the strategy classes trivially testable in isolation.

REGISTRY POLICY (post-data-review of 1741 worker-fired trades):
  - Strategies with persistent negative PnL across multiple coins are not
    exposed via _STRATEGIES so the worker stops firing them. Class files
    stay on disk; re-enable by adding the class to the tuple below.
  - Removed: SwingSRBounce (-97%), MACDCross (-40%), BollingerReversion (-40%),
    Breakout (-32%), BestTrade (-24% / 0% WR), IchimokuCross (-22%),
    SMCTrendLiquidity-style imports never lived here, TrendFollowing (-19%).
  - Confluence is the new combined-edge strategy that votes across the
    surviving profitable strategies; see strategies/confluence.py.
"""
from .base import Strategy

# --- Surviving / profitable strategies ---
from .scalping import ScalpingRSI
from .day_trading import DayTradingEMACross
from .supertrend_flip import SuperTrendFlip
from .donchian_turtle import DonchianTurtle
from .stochastic_rev import StochasticReversal
from .adx_trend import ADXTrend
from .champion import Champion
from .price_action import PriceAction
from .confluence import Confluence
from .ema34_rejection import EMA34Rejection

# --- Class files kept on disk but NOT registered (consistently negative PnL) ---
# from .best import BestTrade            #  0% WR, -23.57% PnL over 18 trades
# from .swing import SwingSRBounce       # 38% WR, -97.67% PnL over 358 trades
# from .trend_following import TrendFollowing  # 51% WR but -19% PnL (bad RR)
# from .breakout import Breakout         # 37% WR, -31.71% PnL
# from .macd_cross import MACDCross      # 13% WR, -39.59% PnL
# from .bollinger_rev import BollingerReversion # 25% WR, -40.12% PnL
# from .ichimoku_cross import IchimokuCross     # 19% WR, -22.44% PnL


# Order matters: Confluence first so the UI surfaces the highest-quality
# meta-strategy at the top of the picker.
_STRATEGIES: dict[str, type[Strategy]] = {
    cls.id: cls for cls in (
        Confluence,
        Champion, PriceAction, EMA34Rejection,
        DonchianTurtle, SuperTrendFlip, StochasticReversal, ADXTrend,
        ScalpingRSI, DayTradingEMACross,
    )
}


def get_strategy(strategy_id: str) -> Strategy:
    cls = _STRATEGIES.get(strategy_id)
    if cls is None:
        raise KeyError(strategy_id)
    return cls()


def list_strategies() -> list[type[Strategy]]:
    return list(_STRATEGIES.values())
