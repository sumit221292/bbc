"""Multi-timeframe strategies — registered separately from single-TF strategies.

These don't fit the standard `Strategy.evaluate(candles)` interface because they
need three timeframes of data. The router special-cases ids that start with
`mtf_` and uses the dispatch table here instead.
"""
from __future__ import annotations

from typing import Callable

from ..multi_tf import (
    MTFContext,
    evaluate_chop_aware,
    evaluate_chop_only,
    evaluate_relaxed,
    evaluate_strict,
    evaluate_2screen,
)
from ..schemas import Signal, StrategyMeta


# id -> (name, description, evaluator function)
_MTF_REGISTRY: dict[str, tuple[str, str, Callable[[MTFContext, int], list[Signal]]]] = {
    "mtf_chop_aware": (
        "★★ MTF Chop-Aware (recommended)",
        "Multi-timeframe: 1d regime + 1h trigger. Pullback longs in uptrend, "
        "pullback shorts in downtrend, RSI+BB reversion in chop. Best balance "
        "of frequency and quality in backtests (+6% over 30 days). "
        "Chart auto-switches to 1h since signals fire on 1h candles.",
        evaluate_chop_aware,
    ),
    "mtf_strict": (
        "MTF Strict (1d + 4h + 1h)",
        "Most selective: requires 1d trend (ADX>=20), 4h alignment, and 1h trigger. "
        "Refuses to trade in chop -- capital just waits. Runs on 1h candles.",
        evaluate_strict,
    ),
    "mtf_2screen": (
        "MTF 2-Screen (1d + 1h)",
        "Daily regime filter + 1h pullback trigger. Skips chop entirely. "
        "Drops 4h confirmation for more signals. Runs on 1h candles.",
        evaluate_2screen,
    ),
    "mtf_chop_only": (
        "MTF Chop-Only (range trader)",
        "Only trades mean-reversion when 1d is in chop. Ignores trends entirely. "
        "Runs on 1h candles.",
        evaluate_chop_only,
    ),
}


def list_mtf_metas() -> list[StrategyMeta]:
    return [StrategyMeta(id=k, name=v[0], description=v[1]) for k, v in _MTF_REGISTRY.items()]


def is_mtf(strategy_id: str) -> bool:
    return strategy_id in _MTF_REGISTRY


def run_mtf(strategy_id: str, ctx: MTFContext, start_idx: int = 0) -> list[Signal]:
    if strategy_id not in _MTF_REGISTRY:
        raise KeyError(strategy_id)
    return _MTF_REGISTRY[strategy_id][2](ctx, start_idx)
