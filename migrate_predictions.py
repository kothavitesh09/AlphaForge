import asyncio
import os
import sys
from pathlib import Path
from pprint import pprint

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))

from app.services.prediction_pipeline import (  # noqa: E402
    REQUIRED_PREDICTION_FIELDS,
    PredictionPipelineService,
    _opportunity_score,
    _predicted_change_percent,
    _predicted_price,
    _target_timestamp,
    _validate_prediction_record,
)


load_dotenv()
load_dotenv(ROOT / "backend" / ".env")

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017/alphaforge")
MONGODB_DATABASE = os.getenv("MONGODB_DATABASE", "alphaforge")


async def main() -> None:
    client = AsyncIOMotorClient(MONGODB_URI, uuidRepresentation="standard", serverSelectionTimeoutMS=5000)
    try:
        await client.admin.command("ping")
        db = client.get_default_database(default=MONGODB_DATABASE)
        print(f"MongoDB: connected database={db.name}")

        audit_before = await audit_predictions(db)
        print("\nAudit before migration:")
        pprint(audit_before)

        service = PredictionPipelineService(db)
        updated = 0
        unchanged = 0
        skipped: list[dict] = []

        cursor = db.predictions.find({}).sort([("created_at", 1)])
        async for prediction in cursor:
            update = await migration_update(service, prediction)
            if update is None:
                unchanged += 1
                continue
            if "skip_reason" in update:
                skipped.append({
                    "id": str(prediction.get("_id")),
                    "symbol": prediction.get("symbol"),
                    "timeframe": prediction.get("timeframe"),
                    "reason": update["skip_reason"],
                })
                continue
            await db.predictions.update_one({"_id": prediction["_id"]}, {"$set": update})
            updated += 1

        audit_after = await audit_predictions(db)
        print("\nMigration summary:")
        pprint({
            "updated": updated,
            "unchanged": unchanged,
            "skipped": len(skipped),
            "skipped_records": skipped[:20],
        })
        print("\nAudit after migration:")
        pprint(audit_after)

        if audit_after["predictions_missing_required_fields"] > 0:
            raise SystemExit("Migration completed with predictions still missing required fields")
    finally:
        client.close()


async def audit_predictions(db) -> dict:
    total = await db.predictions.count_documents({})
    missing_by_field = {
        field: await db.predictions.count_documents({field: {"$exists": False}})
        for field in REQUIRED_PREDICTION_FIELDS
    }
    null_by_field = {
        field: await db.predictions.count_documents({field: None})
        for field in REQUIRED_PREDICTION_FIELDS
    }
    missing_required = await db.predictions.count_documents({
        "$or": [{field: {"$exists": False}} for field in REQUIRED_PREDICTION_FIELDS] + [{field: None} for field in REQUIRED_PREDICTION_FIELDS]
    })
    return {
        "predictions_count": total,
        "predictions_missing_required_fields": missing_required,
        "missing_by_field": missing_by_field,
        "null_by_field": null_by_field,
    }


async def migration_update(service: PredictionPipelineService, prediction: dict) -> dict | None:
    missing = [field for field in REQUIRED_PREDICTION_FIELDS if prediction.get(field) is None]
    if not missing:
        return None

    symbol = str(prediction.get("symbol") or "").upper()
    timeframe = prediction.get("timeframe")
    source_timestamp = prediction.get("source_timestamp") or prediction.get("prediction_timestamp")
    if symbol and timeframe and source_timestamp:
        candles = await stored_candles_until(service.db, symbol, timeframe, source_timestamp)
        if candles:
            record = await service._prediction_record(symbol, timeframe, candles)
            _validate_prediction_record(record)
            return {
                "predicted_price": record["predicted_price"],
                "predicted_change_pct": record["predicted_change_pct"],
                "target_timestamp": record["target_timestamp"],
                "opportunity_score": record["opportunity_score"],
                "expected_move": record.get("expected_move"),
                "prediction_timestamp": record.get("prediction_timestamp"),
                "current_price": record.get("current_price"),
                "updated_at": record.get("updated_at"),
            }

    fallback = fallback_update(prediction)
    if fallback:
        _validate_prediction_record({**prediction, **fallback})
        return fallback
    return {"skip_reason": "missing timeframe/source timestamp/candles for existing prediction logic"}


async def stored_candles_until(db, symbol: str, timeframe: str, source_timestamp: str) -> list[dict]:
    rows = [
        clean(row)
        async for row in db.market_data.find(
            {"symbol": symbol, "interval": timeframe, "timestamp": {"$lte": source_timestamp}},
        ).sort([("timestamp", -1)]).limit(500)
    ]
    rows.reverse()
    return rows


def fallback_update(prediction: dict) -> dict | None:
    source_close = number(prediction.get("source_close") or prediction.get("current_price"))
    confidence = number(prediction.get("confidence")) or 0
    direction = str(prediction.get("direction") or "").upper()
    expected_move = prediction.get("expected_move")
    timeframe = prediction.get("timeframe")
    source_timestamp = prediction.get("source_timestamp") or prediction.get("prediction_timestamp")
    predicted_change_pct = _predicted_change_percent(direction, expected_move)
    predicted_price = _predicted_price(source_close or 0, predicted_change_pct)
    target_timestamp = _target_timestamp(str(timeframe), source_timestamp) if timeframe and source_timestamp else None
    if predicted_change_pct is None or predicted_price is None or target_timestamp is None:
        return None
    return {
        "predicted_change_pct": predicted_change_pct,
        "predicted_price": predicted_price,
        "target_timestamp": target_timestamp,
        "opportunity_score": _opportunity_score(predicted_change_pct, confidence),
        "current_price": source_close,
        "prediction_timestamp": source_timestamp,
    }


def number(value) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def clean(document: dict) -> dict:
    item = dict(document)
    item.pop("_id", None)
    return item


if __name__ == "__main__":
    asyncio.run(main())
