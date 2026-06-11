import asyncio
import sys
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402
from app.services.analytics_engine import AnalyticsEngine, MarketSentimentEngine, SignalValidationService  # noqa: E402
from app.services.ml_dataset import MLDatasetService  # noqa: E402
from app.services.prediction_pipeline import PredictionPipelineService  # noqa: E402


async def main() -> None:
    load_dotenv(ROOT / "backend" / ".env")
    settings = get_settings()
    client = AsyncIOMotorClient(settings.mongodb_uri, uuidRepresentation="standard", serverSelectionTimeoutMS=5000)
    try:
        db = client.get_default_database(default=settings.mongodb_database)
        before = await counts(db)
        pipeline = PredictionPipelineService(db)
        predictions = await pipeline.generate_predictions()
        seeded = await pipeline.seed_evaluable_predictions(samples_per_pair=80)
        evaluated = await pipeline.evaluate_predictions()
        validations = await SignalValidationService(db).validate_all()
        sentiment = await MarketSentimentEngine(db).update()
        analytics = await AnalyticsEngine(db).update()
        dataset = await MLDatasetService(db).build(timeframe="1h", limit_per_symbol=5000)
        after = await counts(db)
        print("before", before)
        print("predictions", {k: v for k, v in predictions.items() if k != "records"})
        print("seeded", seeded)
        print("evaluated", evaluated)
        print("validations", validations)
        print("sentiment", sentiment)
        print("analytics", analytics["metrics"])
        print("ml_dataset", {"row_count": dataset["row_count"], "models": dataset["models"], "timeframe": dataset["timeframe"]})
        print("after", after)
    finally:
        client.close()


async def counts(db) -> dict:
    names = ["analytics_stats", "market_sentiment", "signal_validations", "paper_trades", "portfolio", "portfolios", "predictions", "prediction_results", "accuracy_stats", "ml_datasets"]
    return {name: await db[name].count_documents({}) for name in names}


if __name__ == "__main__":
    asyncio.run(main())
