import asyncio
import sys
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402
from app.services.prediction_pipeline import PredictionPipelineService  # noqa: E402


async def main() -> None:
    load_dotenv(ROOT / "backend" / ".env")
    settings = get_settings()
    client = AsyncIOMotorClient(settings.mongodb_uri, uuidRepresentation="standard", serverSelectionTimeoutMS=5000)
    try:
        db = client.get_default_database(default=settings.mongodb_database)
        pipeline = PredictionPipelineService(db)
        before = await counts(db)
        coverage = await pipeline.candle_coverage()
        predictions = await pipeline.generate_predictions()
        signals = await pipeline.generate_signals()
        seeded = await pipeline.seed_evaluable_predictions()
        evaluated = await pipeline.evaluate_predictions()
        after = await counts(db)
        print("before_counts", before)
        print("oldest_candle", coverage["oldest_candle"])
        print("newest_candle", coverage["newest_candle"])
        print("total_historical_candles", coverage["total_historical_candles"])
        print("prediction_generation", {k: v for k, v in predictions.items() if k != "records"})
        print("signal_generation", {k: v for k, v in signals.items() if k != "records"})
        print("seeded_evaluable_predictions", seeded)
        print("evaluation", evaluated)
        print("after_counts", after)
    finally:
        client.close()


async def counts(db) -> dict:
    names = ["market_data", "indicator_data", "signals", "predictions", "prediction_results", "accuracy_stats"]
    return {name: await db[name].count_documents({}) for name in names}


if __name__ == "__main__":
    asyncio.run(main())
