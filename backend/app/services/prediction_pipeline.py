import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from app.core.config import SUPPORTED_INTERVALS, SUPPORTED_SYMBOLS
from app.services.indicators import calculate_indicators
from app.repositories.base import MongoRepository, now_utc
from app.services.market_data import KoinBXClient
from app.services.prediction import PredictionService
from app.services.sentiment import SentimentService
from app.services.signals import SignalService


logger = logging.getLogger(__name__)

PREDICTION_TIMEFRAMES = ("15m", "1h", "4h", "1d")
REQUIRED_PREDICTION_FIELDS = (
    "predicted_price",
    "predicted_change_pct",
    "target_timestamp",
    "opportunity_score",
)
EVALUATION_HORIZONS = {
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
}


def normalize_timeframe(timeframe: Any, default: str | None = "1h") -> str | None:
    value = str(timeframe or default or "").strip().lower()
    return value if value in PREDICTION_TIMEFRAMES else default


class PredictionPipelineService:
    def __init__(self, db):
        self.db = db
        self.market = KoinBXClient()
        self.predictor = PredictionService()
        self.predictions = MongoRepository(db, "predictions")
        self.results = MongoRepository(db, "prediction_results")
        self.stats = MongoRepository(db, "accuracy_stats")

    async def candle_coverage(self) -> dict:
        oldest = await self.db.market_data.find_one(sort=[("timestamp", 1)])
        newest = await self.db.market_data.find_one(sort=[("timestamp", -1)])
        total = await self.db.market_data.count_documents({})
        rows = [
            _clean(row)
            async for row in self.db.market_data.aggregate(
                [
                    {
                        "$group": {
                            "_id": {"symbol": "$symbol", "interval": "$interval"},
                            "count": {"$sum": 1},
                            "oldest": {"$min": "$timestamp"},
                            "newest": {"$max": "$timestamp"},
                        }
                    },
                    {"$sort": {"_id.symbol": 1, "_id.interval": 1}},
                ]
            )
        ]
        return {
            "total_historical_candles": total,
            "oldest_candle": _candle_ref(oldest),
            "newest_candle": _candle_ref(newest),
            "coverage": rows,
        }

    async def generate_predictions(
        self,
        symbols: list[str] | None = None,
        timeframes: list[str] | None = None,
    ) -> dict:
        symbols = [symbol.upper() for symbol in (symbols or list(SUPPORTED_SYMBOLS)) if symbol.upper() in SUPPORTED_SYMBOLS]
        timeframes = _normalize_timeframes(timeframes)
        created = 0
        skipped: list[dict] = []
        records: list[dict] = []
        for symbol in symbols:
            for timeframe in timeframes:
                candles = await self._stored_candles(symbol, timeframe, limit=500)
                if len(candles) < 1:
                    skipped.append({"symbol": symbol, "timeframe": timeframe, "reason": "not_enough_candles", "candles": len(candles)})
                    continue
                record = await self._prediction_record(symbol, timeframe, candles)
                _validate_prediction_record(record)
                await self.db.predictions.update_one(
                    {"symbol": symbol, "timeframe": timeframe, "source_timestamp": record["source_timestamp"]},
                    {"$set": record, "$setOnInsert": {"created_at": now_utc()}},
                    upsert=True,
                )
                created += 1
                records.append(record)
                logger.info("Prediction Created symbol=%s timeframe=%s direction=%s confidence=%s", symbol, timeframe, record["direction"], record["confidence"])
        return {"created": created, "skipped": skipped, "records": records}

    async def generate_signals(self, symbols: list[str] | None = None) -> dict:
        symbols = [symbol.upper() for symbol in (symbols or list(SUPPORTED_SYMBOLS)) if symbol.upper() in SUPPORTED_SYMBOLS]
        service = SignalService(self.db)
        sentiment_service = SentimentService()
        generated = 0
        skipped: list[dict] = []
        records: list[dict] = []
        for symbol in symbols:
            interval, candles = await self._best_signal_candles(symbol, limit=240)
            if len(candles) < 2:
                skipped.append({"symbol": symbol, "reason": "not_enough_candles", "candles": len(candles)})
                continue
            try:
                order_book = await self.market.order_book(symbol)
            except Exception:
                order_book = {"bids": [], "asks": []}
            sentiment = await sentiment_service.symbol_sentiment(symbol)
            signal = await service.generate(symbol, candles, order_book, sentiment)
            generated += 1
            records.append(signal)
            logger.info("Signal Generated symbol=%s interval=%s signal=%s confidence=%s", symbol, interval, signal.get("signal"), signal.get("confidence"))
        return {"generated": generated, "skipped": skipped, "records": records}

    async def evaluate_predictions(self) -> dict:
        evaluated = 0
        pending = 0
        predictions = self.db.predictions.find({"evaluated": {"$ne": True}}).sort([("created_at", 1)]).limit(5000)
        async for prediction in predictions:
            timeframe = normalize_timeframe(prediction.get("timeframe"), default=None)
            symbol = prediction.get("symbol")
            source_timestamp = prediction.get("source_timestamp")
            horizon = EVALUATION_HORIZONS.get(timeframe)
            if not symbol or not timeframe or not source_timestamp or not horizon:
                continue
            target_time = _parse_time(source_timestamp) + horizon
            result_candle = await self.db.market_data.find_one(
                {"symbol": symbol, "interval": timeframe, "timestamp": {"$gte": _iso(target_time)}},
                sort=[("timestamp", 1)],
            )
            if not result_candle:
                pending += 1
                continue
            start_price = float(prediction.get("source_close") or 0)
            end_price = float(result_candle.get("close") or 0)
            actual = _actual_direction(start_price, end_price)
            expected = str(prediction.get("direction", "")).upper()
            correct = expected == actual
            result = {
                "prediction_id": str(prediction["_id"]),
                "symbol": symbol,
                "timeframe": timeframe,
                "predicted": expected,
                "actual": actual,
                "correct": correct,
                "confidence": float(prediction.get("confidence", 0)),
                "source_timestamp": source_timestamp,
                "resolved_timestamp": result_candle.get("timestamp"),
                "start_price": start_price,
                "end_price": end_price,
                "return_percent": round(((end_price / start_price) - 1) * 100, 4) if start_price else 0,
                "resolved_at": now_utc(),
            }
            await self.db.prediction_results.update_one(
                {"prediction_id": result["prediction_id"]},
                {"$set": result, "$setOnInsert": {"created_at": now_utc()}},
                upsert=True,
            )
            await self.db.predictions.update_one({"_id": prediction["_id"]}, {"$set": {"evaluated": True, "evaluated_at": now_utc()}})
            evaluated += 1
            logger.info("Prediction Evaluated symbol=%s timeframe=%s predicted=%s actual=%s correct=%s", symbol, timeframe, expected, actual, correct)
        stats = await self.update_accuracy_stats()
        return {"evaluated": evaluated, "pending": pending, "accuracy": stats}

    async def seed_evaluable_predictions(
        self,
        symbols: list[str] | None = None,
        timeframes: list[str] | None = None,
        samples_per_pair: int = 3,
    ) -> dict:
        symbols = [symbol.upper() for symbol in (symbols or list(SUPPORTED_SYMBOLS)) if symbol.upper() in SUPPORTED_SYMBOLS]
        timeframes = _normalize_timeframes(timeframes)
        created = 0
        skipped: list[dict] = []
        for symbol in symbols:
            for timeframe in timeframes:
                candles = await self._stored_candles(symbol, timeframe, limit=500)
                horizon = EVALUATION_HORIZONS[timeframe]
                candidates = []
                for index, candle in enumerate(candles[:-1]):
                    target_time = _parse_time(candle["timestamp"]) + horizon
                    if any(_parse_time(future["timestamp"]) >= target_time for future in candles[index + 1 :]):
                        candidates.append(index)
                if not candidates:
                    skipped.append({"symbol": symbol, "timeframe": timeframe, "reason": "no_evaluable_history", "candles": len(candles)})
                    continue
                for index in candidates[-samples_per_pair:]:
                    history = candles[: index + 1]
                    record = await self._prediction_record(symbol, timeframe, history)
                    _validate_prediction_record(record)
                    record["bootstrap_evaluation"] = True
                    await self.db.predictions.update_one(
                        {"symbol": symbol, "timeframe": timeframe, "source_timestamp": record["source_timestamp"]},
                        {"$set": record, "$setOnInsert": {"created_at": now_utc()}},
                        upsert=True,
                    )
                    created += 1
                    logger.info("Prediction Created symbol=%s timeframe=%s direction=%s confidence=%s", symbol, timeframe, record["direction"], record["confidence"])
        return {"created": created, "skipped": skipped}

    async def update_accuracy_stats(self) -> dict:
        rows = [row async for row in self.db.prediction_results.find({}).sort([("resolved_at", -1)]).limit(10000)]
        total = len(rows)
        correct = len([row for row in rows if row.get("correct")])
        avg_confidence = round(sum(float(row.get("confidence", 0)) for row in rows) / total, 2) if total else 0
        summary = {
            "timeframe": "all",
            "total_predictions": total,
            "correct_predictions": correct,
            "incorrect_predictions": total - correct,
            "accuracy_percent": round(correct / total * 100, 2) if total else 0,
            "win_rate": round(correct / total * 100, 2) if total else 0,
            "average_confidence": avg_confidence,
            "created_at": now_utc(),
        }
        await self.db.accuracy_stats.update_one(
            {"timeframe": "all"},
            {"$set": summary, "$setOnInsert": {"first_created_at": now_utc()}},
            upsert=True,
        )
        for timeframe in PREDICTION_TIMEFRAMES:
            scoped = [row for row in rows if normalize_timeframe(row.get("timeframe"), default=None) == timeframe]
            scoped_total = len(scoped)
            scoped_correct = len([row for row in scoped if row.get("correct")])
            scoped_summary = {
                "timeframe": timeframe,
                "total_predictions": scoped_total,
                "correct_predictions": scoped_correct,
                "incorrect_predictions": scoped_total - scoped_correct,
                "accuracy_percent": round(scoped_correct / scoped_total * 100, 2) if scoped_total else 0,
                "win_rate": round(scoped_correct / scoped_total * 100, 2) if scoped_total else 0,
                "average_confidence": round(sum(float(row.get("confidence", 0)) for row in scoped) / scoped_total, 2) if scoped_total else 0,
                "created_at": now_utc(),
            }
            await self.db.accuracy_stats.update_one(
                {"timeframe": timeframe},
                {"$set": scoped_summary, "$setOnInsert": {"first_created_at": now_utc()}},
                upsert=True,
            )
        snapshots = self._accuracy_snapshots(rows)
        if snapshots:
            await self.db.accuracy_stats.insert_many(snapshots)
        logger.info("Accuracy Updated total=%s correct=%s accuracy=%s", total, correct, summary["accuracy_percent"])
        return summary

    def _accuracy_snapshots(self, rows: list[dict]) -> list[dict]:
        snapshots = []
        windows = (25, 50, 100, 250, 500)
        groups: dict[tuple[str, str], list[dict]] = {}
        for row in rows:
            symbol = str(row.get("symbol") or "UNKNOWN")
            timeframe = normalize_timeframe(row.get("timeframe"), default=None) or "UNKNOWN"
            groups.setdefault((symbol, timeframe), []).append(row)
        for (symbol, timeframe), scoped in groups.items():
            for window in windows:
                sample = scoped[:window]
                if not sample:
                    continue
                total = len(sample)
                correct = len([row for row in sample if row.get("correct")])
                snapshots.append({
                    "scope": "rolling",
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "window": window,
                    "sample_size": total,
                    "total_predictions": total,
                    "correct_predictions": correct,
                    "incorrect_predictions": total - correct,
                    "accuracy_percent": round(correct / total * 100, 2) if total else 0,
                    "win_rate": round(correct / total * 100, 2) if total else 0,
                    "average_confidence": round(sum(float(row.get("confidence", 0)) for row in sample) / total, 2) if total else 0,
                    "created_at": now_utc(),
                })
        return snapshots

    async def _stored_candles(self, symbol: str, timeframe: str, limit: int) -> list[dict]:
        timeframe = normalize_timeframe(timeframe) or "1h"
        rows = [
            _clean(row)
            async for row in self.db.market_data.find({"symbol": symbol, "interval": timeframe}).sort([("timestamp", -1)]).limit(limit)
        ]
        rows.reverse()
        return rows

    async def _best_signal_candles(self, symbol: str, limit: int) -> tuple[str, list[dict]]:
        best_interval = "1m"
        best_rows: list[dict] = []
        for interval in ("1h", "15m", "5m", "1m", "4h", "1d"):
            rows = await self._stored_candles(symbol, interval, limit=limit)
            if len(rows) > len(best_rows):
                best_interval = interval
                best_rows = rows
            if len(rows) >= 20:
                break
        return best_interval, best_rows

    async def _prediction_record(self, symbol: str, timeframe: str, candles: list[dict]) -> dict:
        timeframe = normalize_timeframe(timeframe) or "1h"
        latest = candles[-1]
        try:
            model = self.predictor.train_predict(candles, {"bids": [], "asks": []}, {"score": 0})
            probabilities = {
                "up": model["buy_probability"],
                "down": model["sell_probability"],
                "sideways": model["hold_probability"],
            }
            expected_move = model.get("expected_move")
            warning = model.get("model_warning")
            validation_accuracy = model.get("validation_accuracy", 0)
        except ValueError as exc:
            probabilities = self.predictor.rule_probabilities_from_candles(candles)
            expected_move = _expected_move_from_candles(candles)
            warning = str(exc)
            validation_accuracy = 0
        direction = max(probabilities, key=probabilities.get).upper()
        source_close = float(latest.get("close") or 0)
        predicted_change_pct = _predicted_change_percent(direction, expected_move)
        predicted_price = _predicted_price(source_close, predicted_change_pct)
        target_timestamp = _target_timestamp(timeframe, latest["timestamp"])
        confidence = max(probabilities.values())
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "direction": direction,
            "probabilities": probabilities,
            "up": probabilities["up"],
            "down": probabilities["down"],
            "sideways": probabilities["sideways"],
            "confidence": confidence,
            "source_timestamp": latest["timestamp"],
            "source_close": source_close,
            "current_price": source_close,
            "predicted_price": predicted_price,
            "predicted_change_pct": predicted_change_pct,
            "prediction_timestamp": latest["timestamp"],
            "target_timestamp": target_timestamp,
            "expected_move": expected_move,
            "opportunity_score": _opportunity_score(predicted_change_pct, confidence),
            "validation_accuracy": validation_accuracy,
            "model_warning": warning,
            "evaluated": False,
            "updated_at": now_utc(),
        }


def _actual_direction(start_price: float, end_price: float) -> str:
    if start_price <= 0:
        return "SIDEWAYS"
    change = (end_price / start_price) - 1
    if change > 0.003:
        return "UP"
    if change < -0.003:
        return "DOWN"
    return "SIDEWAYS"


def _parse_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _target_timestamp(timeframe: str, source_timestamp: Any) -> str | None:
    horizon = EVALUATION_HORIZONS.get(normalize_timeframe(timeframe, default=None))
    if not horizon:
        return None
    return _iso(_parse_time(source_timestamp) + horizon)


def _normalize_timeframes(timeframes: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for timeframe in timeframes or list(PREDICTION_TIMEFRAMES):
        value = normalize_timeframe(timeframe, default=None)
        if value and value not in normalized:
            normalized.append(value)
    return normalized


def _validate_prediction_record(record: dict) -> None:
    missing = [field for field in REQUIRED_PREDICTION_FIELDS if field not in record]
    nulls = [field for field in REQUIRED_PREDICTION_FIELDS if record.get(field) is None]
    if missing or nulls:
        raise ValueError(f"Prediction record missing required fields missing={missing} null={nulls}")


def _expected_move_from_candles(candles: list[dict]) -> str | None:
    df = calculate_indicators(candles)
    if df.empty:
        return None
    latest = df.iloc[-1]
    return PredictionService().expected_move(float(latest["atr"]), float(latest["close"]), float(latest["trend_strength"]))


def _predicted_change_percent(direction: str, expected_move: Any) -> float | None:
    if direction == "SIDEWAYS":
        return 0.0
    if not isinstance(expected_move, str):
        return None
    values = []
    for part in expected_move.replace("%", "").replace("to", " ").split():
        try:
            values.append(abs(float(part)))
        except ValueError:
            continue
    if not values:
        return None
    magnitude = round(sum(values) / len(values), 4)
    return -magnitude if direction == "DOWN" else magnitude


def _predicted_price(source_close: float, predicted_change_pct: float | None) -> float | None:
    if source_close <= 0 or predicted_change_pct is None:
        return None
    return round(source_close * (1 + predicted_change_pct / 100), 8)


def _opportunity_score(predicted_change_pct: float | None, confidence: float) -> float:
    if predicted_change_pct is None:
        return round(max(0, min(100, confidence * 0.4)), 2)
    return round(max(0, min(100, abs(predicted_change_pct) * 12 + confidence * 0.55)), 2)


def _candle_ref(document: dict | None) -> dict | None:
    if not document:
        return None
    return {key: document.get(key) for key in ("symbol", "interval", "timestamp")}


def _clean(document: dict) -> dict:
    item = dict(document)
    item.pop("_id", None)
    return item
