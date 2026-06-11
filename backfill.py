import asyncio
import os
import sys
import argparse
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient


ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.core.config import get_settings  # noqa: E402
from app.database.mongo import ensure_collections, ensure_indexes  # noqa: E402
from app.services.backfill import BackfillService  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run AlphaForge historical OHLCV backfill using real API candles only.")
    parser.add_argument("--symbols", help="Comma-separated symbols. Defaults to all supported symbols.")
    parser.add_argument("--intervals", help="Comma-separated intervals. Defaults to all supported intervals.")
    parser.add_argument("--max-pages-per-pair", type=int, help="Optional operational cap for smoke tests; omit for full backfill.")
    args = parser.parse_args()
    load_dotenv(ROOT / "backend" / ".env")
    settings = get_settings()
    client = AsyncIOMotorClient(settings.mongodb_uri, uuidRepresentation="standard", serverSelectionTimeoutMS=5000)
    try:
        await client.admin.command("ping")
        db = client.get_default_database(default=settings.mongodb_database)
        await ensure_collections(db)
        await ensure_indexes(db)
        symbols = [item.strip().upper() for item in args.symbols.split(",")] if args.symbols else None
        intervals = [item.strip() for item in args.intervals.split(",")] if args.intervals else None
        result = await BackfillService(db).run(symbols=symbols, intervals=intervals, max_pages_per_pair=args.max_pages_per_pair)
        print(
            "Backfill completed: "
            f"records_downloaded={result['records_downloaded']} inserted={result['inserted']} "
            f"updated={result['updated']} failed={result['failed']}"
        )
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
