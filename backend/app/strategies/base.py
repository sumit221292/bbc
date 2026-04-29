"""Strategy base class.

A Strategy turns a list of Candles into a list of Signals. Subclasses only
need to implement `evaluate`. The base class handles the boring bits like
extracting OHLCV columns and packaging the latest signal.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from ..schemas import Candle, Signal, StrategyMeta


class Strategy(ABC):
    id: ClassVar[str]
    name: ClassVar[str]
    description: ClassVar[str]

    @classmethod
    def meta(cls) -> StrategyMeta:
        return StrategyMeta(id=cls.id, name=cls.name, description=cls.description)

    @abstractmethod
    def evaluate(self, candles: list[Candle]) -> list[Signal]:
        """Return signals for every bar where one is generated.

        Implementations should not include synthetic HOLDs at every bar — only
        the bars that actually fire BUY/SELL. The latest HOLD is synthesised
        by the router if no signal fires on the most recent bar.
        """

    @staticmethod
    def closes(candles: list[Candle]) -> list[float]:
        return [c.close for c in candles]

    @staticmethod
    def highs(candles: list[Candle]) -> list[float]:
        return [c.high for c in candles]

    @staticmethod
    def lows(candles: list[Candle]) -> list[float]:
        return [c.low for c in candles]

    @staticmethod
    def volumes(candles: list[Candle]) -> list[float]:
        return [c.volume for c in candles]
