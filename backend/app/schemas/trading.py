from pydantic import BaseModel, Field


class TradeRequest(BaseModel):
    symbol: str = Field(min_length=2, max_length=20)
    quantity: float = Field(gt=0)


class SignalResponse(BaseModel):
    symbol: str
    signal: str
    score: float
    confidence: float
    explanation: list[str]
    expected_move: str
    expected_window: str
    risk: str
    created_at: str | None = None
