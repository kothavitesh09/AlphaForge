from fastapi import APIRouter
from app.database.mongo import get_database
from app.services.market_data import MarketDataClient
from app.services.decision_engine import InstitutionalDecisionEngine
from app.services.sentiment import SentimentService
from app.services.signals import SignalService
from app.services.prediction_pipeline import PredictionPipelineService


router = APIRouter(prefix="/signals", tags=["Signals"])


@router.get("")
async def signals():
    return await SignalService(get_database()).latest()


@router.post("/generate/all")
async def generate_all_signals(payload: dict | None = None):
    payload = payload or {}
    return await PredictionPipelineService(get_database()).generate_signals(payload.get("symbols"))


@router.post("/evaluate")
async def evaluate_signal(payload: dict):
    return InstitutionalDecisionEngine().decide(payload)


@router.get("/{symbol}")
async def signal(symbol: str):
    db = get_database()
    latest = await SignalService(db).latest(symbol, limit=1)
    if latest:
        return latest[0]
    market = MarketDataClient()
    return await SignalService(db).generate(symbol, await market.candles(symbol), await market.order_book(symbol), await SentimentService().symbol_sentiment(symbol))
