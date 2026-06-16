from fastapi import APIRouter, Depends
from app.core.config import SUPPORTED_SYMBOLS
from app.core.security import decode_token
from app.database.mongo import get_database
from app.repositories.base import MongoRepository
from app.services.analytics_engine import AnalyticsEngine, MarketSentimentEngine, SignalValidationService
from app.services.accuracy import AccuracyService
from app.services.advanced_indicators import persist_latest_indicators
from app.services.backtesting import BacktestingService
from app.services.market_data import MarketDataClient
from app.services.market_trend import MarketTrendEngine
from app.services.ml_dataset import MLDatasetService
from app.services.ml_engine import MLTrainingService
from app.services.prediction_pipeline import PredictionPipelineService
from app.services.settings import SettingsService


router = APIRouter(tags=["Analytics"])


@router.get("/indicators/{symbol}")
async def indicators(symbol: str, timeframe: str = "1h"):
    candles = await MarketDataClient().candles(symbol, timeframe)
    return await persist_latest_indicators(get_database(), symbol, timeframe, candles)


@router.get("/trend/{symbol}")
async def trend(symbol: str, timeframe: str = "1h"):
    return MarketTrendEngine().analyze(await MarketDataClient().candles(symbol, timeframe))


@router.get("/accuracy")
async def accuracy(timeframe: str = "all"):
    return await AccuracyService(get_database()).summary(timeframe)


@router.get("/analytics/stats")
async def analytics_stats():
    return await AnalyticsEngine(get_database()).overview()


@router.post("/analytics/refresh")
async def analytics_refresh():
    db = get_database()
    validations = await SignalValidationService(db).validate_all()
    sentiment = await MarketSentimentEngine(db).update()
    stats = await AnalyticsEngine(db).update()
    return {"validations": validations, "sentiment": sentiment, "stats": stats}


@router.get("/market-sentiment")
async def market_sentiment():
    return await MarketSentimentEngine(get_database()).latest()


@router.post("/market-sentiment/update")
async def update_market_sentiment():
    return await MarketSentimentEngine(get_database()).update()


@router.post("/signals/validate")
async def validate_signals():
    return await SignalValidationService(get_database()).validate_all()


@router.post("/predictions/expand")
async def expand_predictions(payload: dict | None = None):
    payload = payload or {}
    pipeline = PredictionPipelineService(get_database())
    generated = await pipeline.generate_predictions(payload.get("symbols"), payload.get("timeframes"))
    seeded = await pipeline.seed_evaluable_predictions(payload.get("symbols"), payload.get("timeframes"), int(payload.get("samples_per_pair", 50)))
    evaluated = await pipeline.evaluate_predictions()
    return {"generated": generated, "seeded": seeded, "evaluated": evaluated}


@router.post("/ml/datasets/build")
async def build_ml_dataset(payload: dict | None = None):
    payload = payload or {}
    return await MLDatasetService(get_database()).build(payload.get("symbols"), str(payload.get("timeframe", "1h")), int(payload.get("limit_per_symbol", 5000)))


@router.get("/ml/datasets/latest")
async def latest_ml_dataset():
    return await MLDatasetService(get_database()).latest()


@router.post("/ml/train")
async def train_ml(payload: dict | None = None):
    payload = payload or {}
    return await MLTrainingService(get_database()).run(payload.get("symbols"), payload.get("timeframes"), int(payload.get("limit_per_symbol", 10000)))


@router.get("/ml/analytics")
async def ml_analytics():
    return await MLTrainingService(get_database()).dashboard()


@router.post("/backtest/start")
async def backtest_start(payload: dict | None = None):
    payload = payload or {}
    db = get_database()
    symbol = str(payload.get("symbol") or SUPPORTED_SYMBOLS[0]).upper()
    interval = str(payload.get("interval") or payload.get("timeframe") or "1h")
    cursor = db.market_data.find({"symbol": symbol, "interval": interval}).sort([("timestamp", 1)]).limit(5000)
    candles = [item async for item in cursor]
    signals = await MongoRepository(db, "signals").find_many({"symbol": symbol}, limit=1000, sort=[("created_at", -1)])
    return await BacktestingService(db).run(symbol, candles, signals)


@router.get("/backtest/results")
async def backtest_results(symbol: str | None = None):
    query = {"symbol": symbol.upper()} if symbol else {}
    return await MongoRepository(get_database(), "backtest_results").find_many(query, limit=100, sort=[("created_at", -1)])


@router.post("/backtest/{symbol}")
async def backtest(symbol: str, timeframe: str = "1h"):
    db = get_database()
    candles = [item async for item in db.market_data.find({"symbol": symbol.upper(), "interval": timeframe}).sort([("timestamp", 1)]).limit(5000)]
    signals = await MongoRepository(db, "signals").find_many({"symbol": symbol.upper()}, limit=500, sort=[("created_at", -1)])
    return await BacktestingService(db).run(symbol, candles, signals)


@router.get("/settings")
async def get_settings(user_id: str = Depends(decode_token)):
    return await SettingsService(get_database()).get(user_id)


@router.put("/settings")
async def update_settings(payload: dict, user_id: str = Depends(decode_token)):
    return await SettingsService(get_database()).update(user_id, payload)
