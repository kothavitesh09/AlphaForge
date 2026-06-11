import asyncio
import sys
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402
from app.services.ml_engine import MLTrainingService  # noqa: E402


async def main() -> None:
    load_dotenv(ROOT / "backend" / ".env")
    settings = get_settings()
    client = AsyncIOMotorClient(settings.mongodb_uri, uuidRepresentation="standard", serverSelectionTimeoutMS=5000)
    try:
        db = client.get_default_database(default=settings.mongodb_database)
        result = await MLTrainingService(db).run()
        counts = {name: await db[name].count_documents({}) for name in ["ml_features", "ml_labels", "ml_model_results", "ml_model_versions", "ml_predictions", "ensemble_predictions"]}
        dashboard = await MLTrainingService(db).dashboard()
        print("result", slim(result))
        print("counts", counts)
        print("best_model", dashboard.get("best_model"))
        print("top_features", dashboard.get("top_features", [])[:10])
    finally:
        client.close()


def slim(value):
    if isinstance(value, dict):
        return {key: slim(val) for key, val in value.items() if key not in {"skipped"}}
    if isinstance(value, list):
        return [slim(item) for item in value[:12]]
    return value


if __name__ == "__main__":
    asyncio.run(main())
