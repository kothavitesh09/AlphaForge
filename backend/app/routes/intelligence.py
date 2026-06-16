from fastapi import APIRouter, Depends

from app.core.security import decode_token
from app.database.mongo import get_database
from app.repositories.base import MongoRepository
from app.services.intelligence import IntelligenceService


router = APIRouter(tags=["Intelligence"])


@router.get("/forecasts")
async def forecasts():
    return await IntelligenceService(get_database()).forecasts()


@router.get("/forecasts/{symbol}")
async def forecast(symbol: str):
    return await IntelligenceService(get_database()).forecast(symbol)


@router.post("/forecasts/refresh")
async def refresh_forecasts(payload: dict | None = None):
    payload = payload or {}
    return await IntelligenceService(get_database()).refresh_all(payload.get("symbols"))


@router.get("/intelligence")
async def intelligence_dashboard():
    return await IntelligenceService(get_database()).intelligence_dashboard()


@router.get("/alpha-scores")
async def alpha_scores():
    return await MongoRepository(get_database(), "alpha_scores").find_many(limit=200, sort=[("rank", 1), ("alpha_score", -1)])


@router.get("/market-regimes")
async def market_regimes():
    return await MongoRepository(get_database(), "market_regimes").find_many(limit=200, sort=[("confidence", -1)])


@router.get("/opportunities")
async def opportunities():
    db = get_database()
    discovery = await db.opportunity_discovery.find_one({"scope": "latest"}, sort=[("created_at", -1)])
    if discovery and discovery.get("visible_opportunities"):
        return discovery.get("visible_opportunities")
    return await MongoRepository(db, "opportunities").find_many({"symbol": {"$exists": True, "$nin": ["", None]}}, limit=200, sort=[("rank", 1), ("alpha_score", -1)])


@router.get("/ml/monitoring")
async def ml_monitoring():
    return await MongoRepository(get_database(), "ml_monitoring").find_many(limit=200, sort=[("updated_at", -1)])


@router.get("/monitoring")
async def monitoring():
    db = get_database()
    return {
        "system_health": await MongoRepository(db, "system_health").find_many(limit=100, sort=[("updated_at", -1)]),
        "job_runs": await MongoRepository(db, "job_runs").find_many(limit=100, sort=[("started_at", -1)]),
    }


@router.get("/paper-trade/analytics")
async def paper_trade_analytics(user_id: str = Depends(decode_token)):
    return await IntelligenceService(get_database()).paper_trading_analytics(user_id)
