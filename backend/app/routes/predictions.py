from fastapi import APIRouter
from app.database.mongo import get_database
from app.repositories.base import serialize
from app.services.prediction_pipeline import PREDICTION_TIMEFRAMES, PredictionPipelineService, normalize_timeframe


router = APIRouter(prefix="/predictions", tags=["Predictions"])


@router.get("")
async def predictions():
    db = get_database()
    cursor = db.predictions.aggregate(
        [
            {
                "$addFields": {
                    "normalized_symbol": {"$toUpper": {"$toString": {"$ifNull": ["$symbol", ""]}}},
                    "normalized_timeframe": {"$toLower": {"$toString": {"$ifNull": ["$timeframe", ""]}}},
                }
            },
            {"$match": {"normalized_symbol": {"$ne": ""}, "normalized_timeframe": {"$in": list(PREDICTION_TIMEFRAMES)}}},
            {"$sort": {"updated_at": -1, "created_at": -1, "source_timestamp": -1}},
            {"$group": {"_id": {"symbol": "$normalized_symbol", "timeframe": "$normalized_timeframe"}, "document": {"$first": "$$ROOT"}}},
            {"$replaceRoot": {"newRoot": "$document"}},
            {"$sort": {"opportunity_score": -1, "confidence": -1}},
        ]
    )
    rows = []
    async for document in cursor:
        symbol = str(document.get("symbol") or "").upper()
        timeframe = normalize_timeframe(document.get("timeframe"), default=None)
        if not symbol or not timeframe or timeframe not in PREDICTION_TIMEFRAMES:
            continue
        document.pop("normalized_symbol", None)
        document.pop("normalized_timeframe", None)
        document["symbol"] = symbol
        document["timeframe"] = timeframe
        rows.append(serialize(document))
    return rows


@router.post("/generate/all")
async def generate_all_predictions(payload: dict | None = None):
    payload = payload or {}
    return await PredictionPipelineService(get_database()).generate_predictions(payload.get("symbols"), payload.get("timeframes"))


@router.post("/evaluate")
async def evaluate_predictions():
    return await PredictionPipelineService(get_database()).evaluate_predictions()


@router.post("/seed-evaluation")
async def seed_evaluation_predictions(payload: dict | None = None):
    payload = payload or {}
    return await PredictionPipelineService(get_database()).seed_evaluable_predictions(
        payload.get("symbols"),
        payload.get("timeframes"),
        int(payload.get("samples_per_pair", 3)),
    )


@router.post("/{symbol}/generate")
async def generate_prediction(symbol: str, timeframe: str = "1h"):
    return await PredictionPipelineService(get_database()).generate_predictions([symbol], [timeframe])


@router.get("/{symbol}")
async def predictions_for_symbol(symbol: str):
    normalized_symbol = symbol.upper()
    cursor = get_database().predictions.aggregate(
        [
            {
                "$addFields": {
                    "normalized_symbol": {"$toUpper": {"$toString": {"$ifNull": ["$symbol", ""]}}},
                    "normalized_timeframe": {"$toLower": {"$toString": {"$ifNull": ["$timeframe", ""]}}},
                }
            },
            {"$match": {"normalized_symbol": normalized_symbol, "normalized_timeframe": {"$in": list(PREDICTION_TIMEFRAMES)}}},
            {"$sort": {"updated_at": -1, "created_at": -1, "source_timestamp": -1}},
            {"$group": {"_id": "$normalized_timeframe", "document": {"$first": "$$ROOT"}}},
            {"$replaceRoot": {"newRoot": "$document"}},
        ]
    )
    rows = []
    async for document in cursor:
        timeframe = normalize_timeframe(document.get("timeframe"), default=None)
        if not timeframe:
            continue
        document.pop("normalized_symbol", None)
        document.pop("normalized_timeframe", None)
        document["symbol"] = normalized_symbol
        document["timeframe"] = timeframe
        rows.append(serialize(document))
    return rows
