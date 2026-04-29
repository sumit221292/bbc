from typing import Literal, Optional
from pydantic import BaseModel, Field


SignalType = Literal["BUY", "SELL", "HOLD"]
TradeStatus = Literal["WIN", "LOSS", "OPEN"]


class Candle(BaseModel):
    time: int = Field(..., description="UNIX seconds (start of bar)")
    open: float
    high: float
    low: float
    close: float
    volume: float


class Signal(BaseModel):
    time: int
    type: SignalType
    price: float
    reason: str
    entry: Optional[float] = None
    stop_loss: Optional[float] = None
    target: Optional[float] = None
    status: Optional[TradeStatus] = None
    pnl_pct: Optional[float] = None
    closed_at: Optional[int] = None  # bar time the trade resolved (WIN/LOSS)


class StrategyMeta(BaseModel):
    id: str
    name: str
    description: str


class StrategySummary(BaseModel):
    total: int
    closed: int
    wins: int
    losses: int
    open: int
    win_rate: float
    total_pnl_pct: float
    avg_pnl_pct: float


class StrategyResult(BaseModel):
    strategy: str
    symbol: str
    interval: str
    signals: list[Signal]
    latest: Signal
    summary: StrategySummary
