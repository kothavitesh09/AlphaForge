import asyncio
import os
from pprint import pprint
import httpx
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient


load_dotenv()
load_dotenv("backend/.env")

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017/alphaforge")
MONGODB_DATABASE = os.getenv("MONGODB_DATABASE", "alphaforge")
HEALTH_URL = os.getenv("API_HEALTH_URL", "http://127.0.0.1:8000/health")

REQUIRED_PREDICTION_FIELDS = (
    "predicted_price",
    "predicted_change_pct",
    "target_timestamp",
    "opportunity_score",
)

EXPECTED_COLLECTIONS = (
    "market_data",
    "indicator_data",
    "signals",
    "predictions",
    "prediction_results",
    "paper_trades",
    "portfolio",
    "portfolios",
    "accuracy_stats",
    "analytics_stats",
    "backfill_status",
    "backfill_runs",
    "backtest_results",
    "market_sentiment",
    "ml_datasets",
    "ml_features",
    "ml_labels",
    "ml_model_results",
    "ml_model_versions",
    "ml_predictions",
    "ensemble_predictions",
    "signal_validations",
    "settings",
    "users",
)

EXPECTED_INDEXES = {
    "market_data": [("symbol", 1), ("interval", 1), ("timestamp", -1)],
    "indicator_data": [("symbol", 1), ("interval", 1), ("timestamp", -1)],
    "signals": [("symbol", 1), ("created_at", -1)],
    "predictions": [("symbol", 1), ("created_at", -1)],
    "backfill_status": [("symbol", 1), ("interval", 1)],
    "backtest_results": [("symbol", 1), ("created_at", -1)],
    "ml_features": [("symbol", 1), ("timeframe", 1), ("timestamp", -1)],
    "ml_labels": [("symbol", 1), ("timeframe", 1), ("timestamp", -1)],
    "ml_model_results": [("model", 1), ("timeframe", 1), ("created_at", -1)],
    "ml_model_versions": [("model", 1), ("timeframe", 1), ("created_at", -1)],
    "ml_predictions": [("symbol", 1), ("timeframe", 1), ("timestamp", -1), ("model", 1)],
    "ensemble_predictions": [("symbol", 1), ("timeframe", 1), ("timestamp", -1)],
}


async def main() -> None:
    client = AsyncIOMotorClient(MONGODB_URI, uuidRepresentation="standard", serverSelectionTimeoutMS=5000)
    try:
        await client.admin.command("ping")
        db = client.get_default_database(default=MONGODB_DATABASE)
        print(f"MongoDB: connected database={db.name}")

        collections = set(await db.list_collection_names())
        print("\nCollections:")
        for name in EXPECTED_COLLECTIONS:
            print(f"  {name}: {'ok' if name in collections else 'missing'}")

        count = await db.market_data.count_documents({})
        oldest = await db.market_data.find_one(sort=[("timestamp", 1)])
        latest = await db.market_data.find_one(sort=[("timestamp", -1)])
        symbols = await db.market_data.distinct("symbol")
        intervals = await db.market_data.distinct("interval")
        print(f"\nmarket_data_count: {count}")
        print("oldest_candle:")
        pprint(candle_ref(oldest))
        print("newest_candle:")
        pprint(candle_ref(latest))
        print(f"active_symbols: {len(symbols)} {sorted(symbols)}")
        print(f"active_intervals: {sorted(intervals)}")
        print("latest_market_data_record:")
        pprint(latest)

        print("\nStatistics:")
        prediction_field_audit = await predictions_required_field_audit(db)
        pprint({
            "indicator_data_count": await db.indicator_data.count_documents({}),
            "signals_count": await db.signals.count_documents({}),
            "predictions_count": await db.predictions.count_documents({}),
            "predictions_missing_required_fields": prediction_field_audit["predictions_missing_required_fields"],
            "backtest_results_count": await db.backtest_results.count_documents({}),
            "accuracy_stats_count": await db.accuracy_stats.count_documents({}),
            "analytics_stats_count": await db.analytics_stats.count_documents({}),
            "market_sentiment_count": await db.market_sentiment.count_documents({}),
            "signal_validations_count": await db.signal_validations.count_documents({}),
            "ml_datasets_count": await db.ml_datasets.count_documents({}),
            "ml_features_count": await db.ml_features.count_documents({}),
            "ml_labels_count": await db.ml_labels.count_documents({}),
            "ml_model_results_count": await db.ml_model_results.count_documents({}),
            "ml_model_versions_count": await db.ml_model_versions.count_documents({}),
            "ml_predictions_count": await db.ml_predictions.count_documents({}),
            "ensemble_predictions_count": await db.ensemble_predictions.count_documents({}),
        })
        print("\nprediction_required_field_audit:")
        pprint(prediction_field_audit)

        print("\nrecords_per_symbol:")
        pprint(await grouped_counts(db.market_data, "$symbol"))
        print("\nrecords_per_interval:")
        pprint(await grouped_counts(db.market_data, "$interval"))
        print("\nsource_breakdown:")
        pprint(await grouped_counts(db.market_data, "$source"))

        print("\nIndexes:")
        for collection, expected_key in EXPECTED_INDEXES.items():
            indexes = await db[collection].index_information()
            found = any(spec.get("key") == expected_key for spec in indexes.values())
            print(f"  {collection} {expected_key}: {'ok' if found else 'missing'}")
            for index_name, spec in indexes.items():
                print(f"    {index_name}: {spec.get('key')}")

        print("\nCollector:")
        status = await collector_status()
        pprint(status)
        validate_collector_status(status)
    finally:
        client.close()


async def collector_status() -> dict:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(HEALTH_URL)
            response.raise_for_status()
            return response.json()
    except Exception as exc:
        return {"collector": "unknown", "health_url": HEALTH_URL, "error": str(exc)}


def validate_collector_status(status: dict) -> None:
    expected = {
        "mongodb": "connected",
        "collector_running": True,
    }
    failures = [f"{key}={status.get(key)!r}" for key, value in expected.items() if status.get(key) != value]
    if not isinstance(status.get("market_data_count"), int):
        failures.append("market_data_count is not an integer")
    if "last_insert_time" not in status:
        failures.append("last_insert_time is missing")
    if failures:
        raise SystemExit("Collector health validation failed: " + ", ".join(failures))
    print("Collector health validation: ok")


def candle_ref(document: dict | None) -> dict | None:
    if not document:
        return None
    return {key: document.get(key) for key in ("symbol", "interval", "timestamp", "source", "open", "high", "low", "close", "volume")}


async def grouped_counts(collection, field: str) -> dict:
    rows = collection.aggregate([{"$group": {"_id": field, "count": {"$sum": 1}}}, {"$sort": {"_id": 1}}])
    return {str(row["_id"]): row["count"] async for row in rows}


async def predictions_required_field_audit(db) -> dict:
    return {
        "predictions_missing_required_fields": await db.predictions.count_documents({
            "$or": [{field: {"$exists": False}} for field in REQUIRED_PREDICTION_FIELDS] + [{field: None} for field in REQUIRED_PREDICTION_FIELDS]
        }),
        "missing_by_field": {
            field: await db.predictions.count_documents({field: {"$exists": False}})
            for field in REQUIRED_PREDICTION_FIELDS
        },
        "null_by_field": {
            field: await db.predictions.count_documents({field: None})
            for field in REQUIRED_PREDICTION_FIELDS
        },
    }


if __name__ == "__main__":
    asyncio.run(main())
