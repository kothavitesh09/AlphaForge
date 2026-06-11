from fastapi import APIRouter, Depends
from app.core.security import decode_token
from app.database.mongo import get_database
from app.schemas.trading import TradeRequest
from app.services.portfolio import PaperTradingService


router = APIRouter(prefix="/paper-trade", tags=["Paper Trading"])


@router.post("/buy")
async def buy(payload: TradeRequest, user_id: str = Depends(decode_token)):
    return await PaperTradingService(get_database()).buy(user_id, payload.symbol, payload.quantity)


@router.post("/sell")
async def sell(payload: TradeRequest, user_id: str = Depends(decode_token)):
    return await PaperTradingService(get_database()).sell(user_id, payload.symbol, payload.quantity)


@router.get("/portfolio")
async def portfolio(user_id: str = Depends(decode_token)):
    return await PaperTradingService(get_database()).portfolio(user_id)


@router.post("/execute-signal")
async def execute_signal(payload: dict, user_id: str = Depends(decode_token)):
    return await PaperTradingService(get_database()).execute_signal(
        user_id,
        str(payload["signal_id"]),
        float(payload["quantity"]) if payload.get("quantity") else None,
        float(payload.get("risk_fraction", 0.1)),
    )


@router.post("/positions/{position_id}/close")
async def close_position(position_id: str, payload: dict | None = None, user_id: str = Depends(decode_token)):
    payload = payload or {}
    price = float(payload.get("price") or 0)
    if price <= 0:
        portfolio = await PaperTradingService(get_database()).portfolio(user_id)
        position = portfolio.get("positions", {}).get(position_id)
        price = float(position.get("current_price", 0)) if position else 0
    return await PaperTradingService(get_database()).close_position(user_id, position_id, price, "manual_close")
