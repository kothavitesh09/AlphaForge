import logging
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import Any
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.core.config import get_settings
from app.services.advanced_indicators import persist_latest_indicators
from app.services.market_data import MarketDataClient


logger = logging.getLogger(__name__)
prediction_refresh_lock = asyncio.Lock()


@dataclass
class CollectorState:
    running: bool = False
    last_insert_time: str | None = None
    last_error: str | None = None
    last_run_time: str | None = None
    inserted_count: int = 0
    active_provider: str = "coindcx"
    collection_latency_ms: float | None = None


collector_state = CollectorState()


class MarketDataCollector:
    def __init__(self, db: AsyncIOMotorDatabase, market: MarketDataClient | None = None) -> None:
        self.db = db
        self.market = market or MarketDataClient()
        self.symbols = get_settings().collector_symbols
        self.intervals = get_settings().collector_intervals

    async def collect_once(self) -> int:
        collector_state.running = True
        collector_state.last_run_time = _utc_now_iso()
        started_at = perf_counter()
        inserted = 0

        for symbol in self.symbols:
            for interval in self.intervals:
                try:
                    logger.info("Fetching %s interval=%s", symbol, interval)
                    candles = await self.market.candles(symbol, interval=interval, limit=240)
                    collector_state.active_provider = self.market.active_provider
                    if not candles:
                        logger.warning("No candle data returned symbol=%s interval=%s", symbol, interval)
                        continue

                    candle = self._normalize_document(symbol, interval, candles[-1])
                    saved = await self._save_candle(candle)
                    if saved:
                        inserted += 1
                        collector_state.inserted_count += 1
                        collector_state.last_insert_time = candle["timestamp"]
                        logger.info("Saved %s Candle interval=%s", candle["symbol"], candle["interval"])
                    await persist_latest_indicators(self.db, symbol, interval, candles)
                except Exception as exc:
                    collector_state.last_error = str(exc)
                    logger.exception("Collector Exception symbol=%s interval=%s error=%s", symbol, interval, exc)
                    continue
        collector_state.collection_latency_ms = round((perf_counter() - started_at) * 1000, 2)
        if inserted > 0:
            await self._refresh_predictions_after_market_update()
        return inserted

    async def run_forever(self, stop_event: asyncio.Event, interval_seconds: int = 60) -> None:
        collector_state.running = True
        logger.info("Collector Started")
        while not stop_event.is_set():
            try:
                await self.collect_once()
            except Exception as exc:
                collector_state.last_error = str(exc)
                logger.exception("Collector Exception error=%s", exc)
                continue

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
            except asyncio.TimeoutError:
                continue

        collector_state.running = False

    def _normalize_document(self, symbol: str, interval: str, candle: dict[str, Any]) -> dict[str, Any]:
        timestamp = _minute_iso(_parse_datetime(candle.get("timestamp")))
        return {
            "symbol": symbol,
            "interval": interval,
            "open": float(candle.get("open") or 0),
            "high": float(candle.get("high") or 0),
            "low": float(candle.get("low") or 0),
            "close": float(candle.get("close") or 0),
            "volume": float(candle.get("volume") or 0),
            "timestamp": timestamp,
            "source": str(candle.get("source") or self.market.active_provider or "coindcx"),
            "updated_at": datetime.now(timezone.utc),
        }

    async def _save_candle(self, candle: dict[str, Any]) -> bool:
        query = {"symbol": candle["symbol"], "interval": candle["interval"], "timestamp": candle["timestamp"]}
        update = {"$set": candle, "$setOnInsert": {"created_at": datetime.now(timezone.utc)}}
        result = await self.db.market_data.update_one(
            query,
            update,
            upsert=True,
        )
        return result.upserted_id is not None

    async def _refresh_predictions_after_market_update(self) -> None:
        if prediction_refresh_lock.locked():
            logger.info("Prediction refresh skipped because previous refresh is still running")
            return
        async with prediction_refresh_lock:
            try:
                from app.services.analytics_engine import AnalyticsEngine, MarketSentimentEngine, SignalValidationService
                from app.services.performance_engine import PerformanceEngine
                from app.services.prediction_pipeline import PredictionPipelineService

                pipeline = PredictionPipelineService(self.db)
                prediction_result = await pipeline.generate_predictions()
                await pipeline.evaluate_predictions()
                await SignalValidationService(self.db).validate_all()
                await PerformanceEngine(self.db).refresh()
                await MarketSentimentEngine(self.db).update()
                await AnalyticsEngine(self.db).update()
                logger.info(
                    "Prediction refresh after market update generated=%s skipped=%s",
                    prediction_result.get("generated"),
                    prediction_result.get("skipped_count"),
                )
            except Exception as exc:
                collector_state.last_error = str(exc)
                logger.exception("Prediction refresh after market update failed error=%s", exc)


async def collector_health(db: AsyncIOMotorDatabase) -> dict[str, Any]:
    count = await db.market_data.count_documents({})
    latest = await db.market_data.find_one(sort=[("timestamp", -1)])
    latest_timestamp = latest.get("timestamp") if latest else None
    return {
        "collector": "running" if collector_state.running else "stopped",
        "last_insert_time": latest_timestamp or collector_state.last_insert_time,
        "last_run_time": collector_state.last_run_time,
        "last_error": collector_state.last_error,
        "market_data_count": count,
        "latest_market_data_timestamp": latest_timestamp,
        "active_provider": collector_state.active_provider,
        "latest_candle_timestamp": latest_timestamp,
        "collection_latency_ms": collector_state.collection_latency_ms,
    }


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)) or str(value).isdigit():
        numeric = float(value)
        dt = datetime.fromtimestamp(numeric / 1000 if numeric > 10_000_000_000 else numeric, timezone.utc)
    elif value:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    else:
        dt = datetime.now(timezone.utc)
    return dt.astimezone(timezone.utc)


def _minute_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(second=0, microsecond=0).isoformat().replace("+00:00", "Z")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
