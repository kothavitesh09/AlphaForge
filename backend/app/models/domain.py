from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


SignalType = Literal["BUY", "SELL", "HOLD"]
RiskLevel = Literal["Low", "Medium", "High"]


class Coin(BaseModel):
    symbol: str
    last: float
    change_24h: float = 0
    volume_24h: float = 0


class Signal(BaseModel):
    symbol: str
    signal: SignalType
    score: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=100)
    explanation: list[str]
    expected_move: str
    expected_window: str
    risk: RiskLevel
    created_at: datetime


class PredictionResult(BaseModel):
    symbol: str
    predicted_direction: SignalType
    actual_direction: SignalType
    correct: bool
    resolved_at: datetime
