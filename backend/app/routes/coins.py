from fastapi import APIRouter
from app.database.mongo import get_database
from app.services.dashboard import DashboardService
from app.services.market_data import KoinBXClient


router = APIRouter(prefix="/coins", tags=["Coins"])


@router.get("")
async def coins():
    return await DashboardService(get_database()).coin_rows()


@router.get("/{symbol}")
async def coin(symbol: str):
    market = KoinBXClient()
    return {"ticker": await market.ticker(symbol), "candles": await market.candles(symbol), "order_book": await market.order_book(symbol)}
