import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from bson import ObjectId
from app.core.config import SUPPORTED_INTERVALS, SUPPORTED_SYMBOLS
from app.services.indicators import calculate_indicators
from app.repositories.base import MongoRepository, now_utc
from app.services.market_data import MarketDataClient
from app.services.performance_engine import PerformanceEngine
from app.services.prediction import PredictionService
from app.services.sentiment import SentimentService
from app.services.signals import SignalService
from app.services.trade_lifecycle import TradeLifecycleEngine


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
        self.market = MarketDataClient()
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
        refresh_rankings: bool = True,
    ) -> dict:
        run_started = now_utc()
        symbols = [symbol.upper() for symbol in (symbols or list(SUPPORTED_SYMBOLS)) if symbol.upper() in SUPPORTED_SYMBOLS]
        timeframes = _normalize_timeframes(timeframes)
        generated = 0
        inserted = 0
        updated = 0
        skipped: list[dict] = []
        records: list[dict] = []
        for symbol in symbols:
            for timeframe in timeframes:
                candles = await self._stored_candles(symbol, timeframe, limit=500)
                if len(candles) < 2:
                    skipped.append({"symbol": symbol, "timeframe": timeframe, "reason": "not_enough_candles", "candles": len(candles)})
                    continue
                record = await self._prediction_record(symbol, timeframe, candles)
                _validate_prediction_record(record)
                result = await self.db.predictions.update_one(
                    {"symbol": symbol, "timeframe": timeframe, "source_timestamp": record["source_timestamp"]},
                    {"$set": record, "$setOnInsert": {"created_at": now_utc()}},
                    upsert=True,
                )
                if result.upserted_id:
                    inserted += 1
                else:
                    updated += 1
                saved = await self.db.predictions.find_one({"symbol": symbol, "timeframe": timeframe, "source_timestamp": record["source_timestamp"]})
                if saved:
                    await PerformanceEngine(self.db).ensure_prediction_validation(saved)
                generated += 1
                records.append(record)
                logger.info("Prediction Created symbol=%s timeframe=%s direction=%s confidence=%s", symbol, timeframe, record["direction"], record["confidence"])
        stale = await self.cleanup_stale_predictions()
        diagnostics = await self._store_generation_diagnostics(run_started, generated, skipped, inserted, updated, stale)
        ranking_refresh: dict[str, Any] | None = None
        if refresh_rankings and generated:
            try:
                from app.services.intelligence import IntelligenceService

                ranking_refresh = await IntelligenceService(self.db).refresh_all(symbols)
            except Exception as exc:
                logger.warning("Opportunity ranking refresh failed after prediction generation: %s", exc)
        return {
            "created": generated,
            "generated": generated,
            "inserted": inserted,
            "updated": updated,
            "skipped_count": len(skipped),
            "skipped": skipped,
            "stale_marked": stale,
            "diagnostics": diagnostics,
            "ranking_refresh": ranking_refresh,
            "records": records,
        }

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
            predicted_price = prediction.get("predicted_price")
            price_error = _price_error(predicted_price, end_price)
            source_type = "bootstrap" if prediction.get("bootstrap_evaluation") else "live"
            result = {
                "prediction_id": str(prediction["_id"]),
                "symbol": symbol,
                "timeframe": timeframe,
                "source_type": source_type,
                "predicted": expected,
                "actual": actual,
                "correct": correct,
                "confidence": float(prediction.get("confidence", 0)),
                "predicted_price": predicted_price,
                "source_timestamp": source_timestamp,
                "resolved_timestamp": result_candle.get("timestamp"),
                "start_price": start_price,
                "end_price": end_price,
                "absolute_error": price_error["absolute_error"],
                "absolute_percentage_error": price_error["absolute_percentage_error"],
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
                    record = await self._prediction_record(symbol, timeframe, history, live=False)
                    _validate_prediction_record(record)
                    record["bootstrap_evaluation"] = True
                    await self.db.predictions.update_one(
                        {"symbol": symbol, "timeframe": timeframe, "source_timestamp": record["source_timestamp"]},
                        {"$set": record, "$setOnInsert": {"created_at": now_utc()}},
                        upsert=True,
                    )
                    saved = await self.db.predictions.find_one({"symbol": symbol, "timeframe": timeframe, "source_timestamp": record["source_timestamp"]})
                    if saved:
                        await PerformanceEngine(self.db).ensure_prediction_validation(saved)
                    created += 1
                    logger.info("Prediction Created symbol=%s timeframe=%s direction=%s confidence=%s", symbol, timeframe, record["direction"], record["confidence"])
        return {"created": created, "skipped": skipped}

    async def update_accuracy_stats(self) -> dict:
        rows = [row async for row in self.db.prediction_results.find({}).sort([("resolved_at", -1)]).limit(10000)]
        rows = await self._hydrate_result_metrics(rows)
        summary = await self._store_accuracy_summary(rows, "all", "all")
        for source_type in ("live", "bootstrap"):
            await self._store_accuracy_summary([row for row in rows if row.get("source_type", "live") == source_type], "all", source_type)
        for timeframe in PREDICTION_TIMEFRAMES:
            scoped = [row for row in rows if normalize_timeframe(row.get("timeframe"), default=None) == timeframe]
            await self._store_accuracy_summary(scoped, timeframe, "all")
            for source_type in ("live", "bootstrap"):
                await self._store_accuracy_summary([row for row in scoped if row.get("source_type", "live") == source_type], timeframe, source_type)
        snapshots = self._accuracy_snapshots(rows)
        if snapshots:
            await self.db.accuracy_stats.insert_many(snapshots)
        logger.info("Accuracy Updated total=%s correct=%s accuracy=%s", summary["total_predictions"], summary["correct_predictions"], summary["accuracy_percent"])
        return summary

    async def _store_accuracy_summary(self, rows: list[dict], timeframe: str, source_type: str) -> dict:
        total = len(rows)
        correct = len([row for row in rows if row.get("correct")])
        avg_confidence = round(sum(float(row.get("confidence", 0)) for row in rows) / total, 2) if total else 0
        abs_errors = [float(row.get("absolute_error", 0)) for row in rows if row.get("absolute_error") is not None]
        ape = [float(row.get("absolute_percentage_error", 0)) for row in rows if row.get("absolute_percentage_error") is not None]
        squared = [value * value for value in abs_errors]
        summary = {
            "timeframe": timeframe,
            "source_type": source_type,
            "total_predictions": total,
            "correct_predictions": correct,
            "incorrect_predictions": total - correct,
            "accuracy_percent": round(correct / total * 100, 2) if total else 0,
            "win_rate": round(correct / total * 100, 2) if total else 0,
            "average_confidence": avg_confidence,
            "mae": round(sum(abs_errors) / len(abs_errors), 6) if abs_errors else 0,
            "mape": round(sum(ape) / len(ape), 6) if ape else 0,
            "rmse": round((sum(squared) / len(squared)) ** 0.5, 6) if squared else 0,
            "created_at": now_utc(),
        }
        await self.db.accuracy_stats.update_one(
            {"timeframe": timeframe, "source_type": source_type, "scope": "summary"},
            {"$set": summary, "$setOnInsert": {"first_created_at": now_utc()}},
            upsert=True,
        )
        return summary

    async def _hydrate_result_metrics(self, rows: list[dict]) -> list[dict]:
        hydrated = []
        for row in rows:
            update = {}
            if row.get("source_type") is None or row.get("absolute_error") is None:
                prediction = await _prediction_for_result(self.db, row)
                if prediction:
                    if row.get("source_type") is None:
                        update["source_type"] = "bootstrap" if prediction.get("bootstrap_evaluation") else "live"
                    if row.get("absolute_error") is None:
                        price_error = _price_error(prediction.get("predicted_price"), float(row.get("end_price", 0) or 0))
                        update.update(price_error)
                        update["predicted_price"] = prediction.get("predicted_price")
            if update:
                await self.db.prediction_results.update_one({"_id": row["_id"]}, {"$set": update})
                row.update(update)
            hydrated.append(row)
        return hydrated

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
                    "source_type": "all",
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

    async def _prediction_record(self, symbol: str, timeframe: str, candles: list[dict], live: bool = True) -> dict:
        return await self._build_prediction_record(symbol, timeframe, candles, live=live)

    async def _build_prediction_record(self, symbol: str, timeframe: str, candles: list[dict], live: bool) -> dict:
        timeframe = normalize_timeframe(timeframe) or "1h"
        latest = candles[-1]
        generated_at = now_utc()
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
        predicted_change_pct = _predicted_change_percent(direction, expected_move, probabilities, candles)
        predicted_price = _predicted_price(source_close, predicted_change_pct)
        target_base = generated_at if live else latest["timestamp"]
        target_timestamp = _target_timestamp(timeframe, target_base)
        confidence = max(probabilities.values())
        lifecycle = await TradeLifecycleEngine(self.db).build(
            symbol=symbol,
            timeframe=timeframe,
            candles=candles,
            probabilities=probabilities,
            model_confidence=confidence,
            predicted_return_pct=predicted_change_pct,
            generated_at=generated_at,
        )
        predicted_change_pct = float(lifecycle.get("predicted_return_pct", predicted_change_pct or 0))
        predicted_price = lifecycle.get("predicted_price") or predicted_price
        direction = str(lifecycle.get("predicted_direction") or direction).upper()
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
            "prediction_timestamp": generated_at,
            "target_timestamp": target_timestamp,
            "expected_move": expected_move,
            "opportunity_score": lifecycle.get("opportunity_score_v2") or _opportunity_score(predicted_change_pct, confidence),
            "validation_accuracy": validation_accuracy,
            "model_warning": warning,
            **lifecycle,
            "stale": False,
            "evaluated": False,
            "updated_at": now_utc(),
        }

    async def cleanup_stale_predictions(self) -> int:
        now_iso = _iso(now_utc())
        result = await self.db.predictions.update_many(
            {
                "bootstrap_evaluation": {"$ne": True},
                "target_timestamp": {"$lte": now_iso},
                "stale": {"$ne": True},
            },
            {"$set": {"stale": True, "stale_at": now_utc()}},
        )
        return int(result.modified_count or 0)

    async def diagnostics(self) -> dict:
        last_run = await self.db.job_runs.find_one({"job": "prediction_generation"}, sort=[("started_at", -1)])
        latest_by_timeframe = await self._latest_prediction_timestamps({"timeframe": "$timeframe"})
        latest_by_coin = await self._latest_prediction_timestamps({"symbol": "$symbol"})
        latest_by_pair = await self._latest_prediction_timestamps({"symbol": "$symbol", "timeframe": "$timeframe"})
        return {
            "last_prediction_generation_time": last_run.get("started_at") if last_run else None,
            "last_prediction_generation_finished_at": last_run.get("finished_at") if last_run else None,
            "last_predictions_generated_count": (last_run.get("metadata") or {}).get("generated", 0) if last_run else 0,
            "last_predictions_skipped_count": (last_run.get("metadata") or {}).get("skipped", 0) if last_run else 0,
            "latest_prediction_timestamp_per_timeframe": latest_by_timeframe,
            "latest_prediction_timestamp_per_coin": latest_by_coin,
            "latest_prediction_timestamp_per_coin_timeframe": latest_by_pair,
        }

    async def _store_generation_diagnostics(
        self,
        started_at: datetime,
        generated: int,
        skipped: list[dict],
        inserted: int,
        updated: int,
        stale: int,
    ) -> dict:
        finished_at = now_utc()
        duration_ms = round((finished_at - started_at).total_seconds() * 1000, 2)
        metadata = {
            "generated": generated,
            "skipped": len(skipped),
            "inserted": inserted,
            "updated": updated,
            "stale_marked": stale,
            "duration_ms": duration_ms,
            "latest_by_timeframe": await self._latest_prediction_timestamps({"timeframe": "$timeframe"}),
            "latest_by_coin": await self._latest_prediction_timestamps({"symbol": "$symbol"}),
        }
        await self.db.job_runs.insert_one(
            {
                "job": "prediction_generation",
                "status": "completed",
                "started_at": started_at,
                "finished_at": finished_at,
                "duration_ms": duration_ms,
                "metadata": metadata,
                "created_at": finished_at,
            }
        )
        await self.db.system_health.update_one(
            {"component": "prediction_generation"},
            {
                "$set": {
                    "component": "prediction_generation",
                    "status": "healthy",
                    "last_latency_ms": metadata.get("duration_ms"),
                    "last_error": None,
                    "updated_at": finished_at,
                    "metadata": metadata,
                },
                "$setOnInsert": {"created_at": finished_at},
            },
            upsert=True,
        )
        return metadata

    async def _latest_prediction_timestamps(self, group_id: dict) -> list[dict]:
        rows = []
        async for row in self.db.predictions.aggregate(
            [
                {"$match": {"bootstrap_evaluation": {"$ne": True}, "stale": {"$ne": True}, "target_timestamp": {"$gt": _iso(now_utc())}}},
                {
                    "$group": {
                        "_id": group_id,
                        "latest_prediction_timestamp": {"$max": "$prediction_timestamp"},
                        "latest_target_timestamp": {"$max": "$target_timestamp"},
                        "count": {"$sum": 1},
                    }
                },
                {"$sort": {"latest_prediction_timestamp": -1}},
            ]
        ):
            item = {"latest_prediction_timestamp": row.get("latest_prediction_timestamp"), "latest_target_timestamp": row.get("latest_target_timestamp"), "count": row.get("count", 0)}
            key = row.get("_id")
            if isinstance(key, dict):
                item.update(key)
            else:
                item["key"] = key
            rows.append(item)
        return rows


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


def _predicted_change_percent(direction: str, expected_move: Any, probabilities: dict | None = None, candles: list[dict] | None = None) -> float | None:
    if not isinstance(expected_move, str):
        expected_move = None
    values = []
    if isinstance(expected_move, str):
        for part in expected_move.replace("%", "").replace("to", " ").split():
            try:
                values.append(abs(float(part)))
            except ValueError:
                continue
    magnitude = round(sum(values) / len(values), 4) if values else _recent_move_magnitude(candles or [])
    if not magnitude:
        return None
    if direction == "SIDEWAYS":
        up = float((probabilities or {}).get("up") or 0)
        down = float((probabilities or {}).get("down") or 0)
        bias = (up - down) / 100
        if abs(bias) < 0.05:
            bias = _recent_direction_bias(candles or [])
        if abs(bias) < 0.02:
            bias = 0.02
        return round(max(-magnitude, min(magnitude, magnitude * bias)), 4)
    return -magnitude if direction == "DOWN" else magnitude


def _predicted_price(source_close: float, predicted_change_pct: float | None) -> float | None:
    if source_close <= 0 or predicted_change_pct is None:
        return None
    return round(source_close * (1 + predicted_change_pct / 100), 8)


def _price_error(predicted_price: Any, actual_price: float) -> dict:
    if predicted_price is None or actual_price <= 0:
        return {"absolute_error": None, "absolute_percentage_error": None}
    absolute_error = abs(float(predicted_price) - actual_price)
    return {
        "absolute_error": round(absolute_error, 8),
        "absolute_percentage_error": round(absolute_error / actual_price * 100, 8),
    }


async def _prediction_for_result(db, result: dict) -> dict | None:
    prediction_id = result.get("prediction_id")
    if not prediction_id:
        return None
    try:
        return await db.predictions.find_one({"_id": ObjectId(str(prediction_id))})
    except Exception:
        return None


def _opportunity_score(predicted_change_pct: float | None, confidence: float) -> float:
    if predicted_change_pct is None:
        return round(max(0, min(100, confidence * 0.4)), 2)
    return round(max(0, min(100, abs(predicted_change_pct) * 12 + confidence * 0.55)), 2)


def _recent_move_magnitude(candles: list[dict]) -> float | None:
    if len(candles) < 2:
        return None
    latest = float(candles[-1].get("close") or 0)
    previous = float(candles[-2].get("close") or 0)
    if latest <= 0 or previous <= 0:
        return None
    return round(max(0.05, min(3.0, abs((latest / previous - 1) * 100))), 4)


def _recent_direction_bias(candles: list[dict]) -> float:
    if len(candles) < 2:
        return 0.0
    latest = float(candles[-1].get("close") or 0)
    previous = float(candles[-2].get("close") or 0)
    if latest > previous:
        return 0.2
    if latest < previous:
        return -0.2
    return 0.0


def _candle_ref(document: dict | None) -> dict | None:
    if not document:
        return None
    return {key: document.get(key) for key in ("symbol", "interval", "timestamp")}


def _clean(document: dict) -> dict:
    item = dict(document)
    item.pop("_id", None)
    return item
