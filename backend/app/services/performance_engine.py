import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean, pstdev
from typing import Any
from bson import ObjectId
from app.repositories.base import MongoRepository, now_utc


WINDOWS = {"7d": 7, "30d": 30, "90d": 90}
SCORE_BUCKETS = ((90, 100, "90-100"), (80, 89.999, "80-89"), (70, 79.999, "70-79"), (60, 69.999, "60-69"), (0, 59.999, "below 60"))
CONFIDENCE_BUCKETS = ((90, 95, "90-95"), (80, 89.999, "80-90"), (70, 79.999, "70-80"), (60, 69.999, "60-70"), (50, 59.999, "50-60"), (0, 49.999, "below 50"))
CORE_ASSETS = {"BTC_INR", "BDX_INR"}


class PerformanceEngine:
    def __init__(self, db):
        self.db = db

    async def refresh(self) -> dict:
        created_validations = await self.ensure_prediction_validations()
        evaluated_predictions = await self.evaluate_prediction_validations()
        created_lifecycle_validations = await self.ensure_lifecycle_validations()
        evaluated_lifecycle_validations = await self.evaluate_lifecycle_validations()
        reality_stats = await self.store_prediction_reality_stats()
        adaptive_learning = await self.store_adaptive_learning_stats()
        dynamic_weights = await self.update_dynamic_model_weights()
        alphaforge_score = await self.store_alphaforge_score()
        opportunity_discovery = await self.store_opportunity_discovery()
        created_trades = await self.ensure_simulated_trades()
        evaluated_trades = await self.evaluate_simulated_trades()
        snapshots = await self.store_performance_snapshots()
        score_buckets = await self.store_opportunity_score_validation()
        calibration = await self.store_confidence_calibration()
        tournament = await self.store_model_tournament()
        allocation = await self.store_allocation_recommendations()
        return {
            "prediction_validations_created": created_validations,
            "prediction_validations_evaluated": evaluated_predictions,
            "lifecycle_validations_created": created_lifecycle_validations,
            "lifecycle_validations_evaluated": evaluated_lifecycle_validations,
            "prediction_reality_stats": reality_stats,
            "adaptive_learning_stats": adaptive_learning,
            "dynamic_model_weights": dynamic_weights,
            "alphaforge_score": alphaforge_score,
            "opportunity_discovery": opportunity_discovery,
            "simulated_trades_created": created_trades,
            "simulated_trades_evaluated": evaluated_trades,
            "performance_snapshots": snapshots,
            "opportunity_score_buckets": score_buckets,
            "confidence_calibration": calibration,
            "model_tournament": tournament,
            "allocation": allocation,
        }

    async def ensure_prediction_validations(self) -> int:
        created = 0
        async for prediction in self.db.predictions.find({}):
            created += await self.ensure_prediction_validation(prediction)
        return int(created)

    async def ensure_prediction_validation(self, prediction: dict) -> int:
        if not prediction.get("target_timestamp") or not prediction.get("_id"):
            return 0
        prediction_id = str(prediction["_id"])
        source_type = "bootstrap" if prediction.get("bootstrap_evaluation") else "live"
        doc = {
            "prediction_id": prediction_id,
            "symbol": prediction.get("symbol"),
            "timeframe": prediction.get("timeframe"),
            "model": prediction.get("model") or prediction.get("model_name") or "rule_engine",
            "source_type": source_type,
            "status": "pending",
            "prediction_timestamp": prediction.get("prediction_timestamp") or prediction.get("source_timestamp"),
            "target_timestamp": prediction.get("target_timestamp"),
            "current_price": float(prediction.get("current_price") or prediction.get("source_close") or 0),
            "predicted_price": _optional_float(prediction.get("predicted_price")),
            "predicted_high": _optional_float(prediction.get("predicted_high")),
            "predicted_low": _optional_float(prediction.get("predicted_low")),
            "predicted_direction": str(prediction.get("direction") or "").upper(),
            "confidence": float(prediction.get("confidence_score") or prediction.get("confidence") or 0),
            "opportunity_score": float(prediction.get("opportunity_score_v2") or prediction.get("opportunity_score") or 0),
            "created_at": now_utc(),
            "updated_at": now_utc(),
        }
        result = await self.db.prediction_validations.update_one(
            {"prediction_id": prediction_id},
            {"$setOnInsert": doc},
            upsert=True,
        )
        return int(result.upserted_id is not None)

    async def evaluate_prediction_validations(self) -> int:
        evaluated = 0
        now_iso = _iso(now_utc())
        cursor = self.db.prediction_validations.find({"status": "pending", "target_timestamp": {"$lte": now_iso}})
        async for validation in cursor:
            symbol = validation.get("symbol")
            timeframe = validation.get("timeframe")
            target_timestamp = validation.get("target_timestamp")
            if not symbol or not timeframe or not target_timestamp:
                continue
            candle = await self.db.market_data.find_one(
                {"symbol": symbol, "interval": timeframe, "timestamp": {"$gte": target_timestamp}},
                sort=[("timestamp", 1)],
            )
            if not candle:
                continue
            current_price = float(validation.get("current_price") or 0)
            actual_price = float(candle.get("close") or 0)
            predicted_price = validation.get("predicted_price")
            actual_direction = _actual_direction(current_price, actual_price)
            predicted_direction = str(validation.get("predicted_direction") or "").upper()
            errors = _price_errors(predicted_price, actual_price)
            result = {
                "status": "evaluated",
                "actual_price": actual_price,
                "actual_direction": actual_direction,
                "direction_correct": predicted_direction == actual_direction,
                "price_error": None if predicted_price is None else round(float(predicted_price) - actual_price, 8),
                "absolute_error": errors["absolute_error"],
                "percentage_error": errors["percentage_error"],
                "resolved_timestamp": candle.get("timestamp"),
                "evaluated_at": now_utc(),
                "updated_at": now_utc(),
            }
            await self.db.prediction_validations.update_one({"_id": validation["_id"]}, {"$set": result})
            await self._mirror_prediction_result(validation, result)
            evaluated += 1
        return evaluated

    async def ensure_lifecycle_validations(self) -> int:
        created = 0
        async for prediction in self.db.predictions.find({"expected_peak_time": {"$exists": True}, "expected_pullback_time": {"$exists": True}}):
            created += await self.ensure_lifecycle_validation(prediction)
        return int(created)

    async def ensure_lifecycle_validation(self, prediction: dict) -> int:
        if not prediction.get("_id"):
            return 0
        prediction_id = str(prediction["_id"])
        doc = {
            "prediction_id": prediction_id,
            "symbol": prediction.get("symbol"),
            "timeframe": prediction.get("timeframe"),
            "status": "pending",
            "source_type": "bootstrap" if prediction.get("bootstrap_evaluation") else "live",
            "prediction_timestamp": prediction.get("prediction_timestamp") or prediction.get("source_timestamp"),
            "current_price": _optional_float(prediction.get("current_price") or prediction.get("source_close")) or 0,
            "expected_peak_price": _optional_float(prediction.get("expected_peak_price")),
            "expected_peak_time": prediction.get("expected_peak_time"),
            "expected_pullback_price": _optional_float(prediction.get("expected_pullback_price")),
            "expected_pullback_time": prediction.get("expected_pullback_time"),
            "expected_return": _optional_float(prediction.get("predicted_return_pct") or prediction.get("predicted_change_pct")) or 0,
            "expected_drawdown": _optional_float(prediction.get("expected_drawdown") or prediction.get("expected_drawdown_pct")) or 0,
            "target_1": _optional_float(prediction.get("target_1") or prediction.get("take_profit_1")),
            "target_2": _optional_float(prediction.get("target_2") or prediction.get("take_profit_2")),
            "target_3": _optional_float(prediction.get("target_3") or prediction.get("take_profit_3") or prediction.get("expected_peak_price")),
            "stop_loss": _optional_float(prediction.get("stop_loss")),
            "market_regime": prediction.get("market_regime"),
            "trading_style": prediction.get("setup_type") or prediction.get("trading_style") or _style_from_prediction(prediction),
            "risk_reward_value": _optional_float(prediction.get("risk_reward_value")) or _risk_reward_from_text(prediction.get("risk_reward_ratio")),
            "confidence": float(prediction.get("confidence_score") or prediction.get("confidence") or 0),
            "calibrated_confidence": float(prediction.get("calibrated_confidence") or prediction.get("confidence_score") or prediction.get("confidence") or 0),
            "opportunity_score_v2": float(prediction.get("opportunity_score_v2") or prediction.get("opportunity_score") or 0),
            "created_at": now_utc(),
            "updated_at": now_utc(),
        }
        result = await self.db.prediction_lifecycle_validations.update_one(
            {"prediction_id": prediction_id},
            {"$setOnInsert": doc},
            upsert=True,
        )
        return int(result.upserted_id is not None)

    async def evaluate_lifecycle_validations(self) -> int:
        updated = 0
        now_iso = _iso(now_utc())
        cursor = self.db.prediction_lifecycle_validations.find({"status": {"$in": ["pending", "peak_evaluated"]}, "$or": [{"expected_peak_time": {"$lte": now_iso}}, {"expected_pullback_time": {"$lte": now_iso}}]})
        async for validation in cursor:
            symbol = validation.get("symbol")
            timeframe = validation.get("timeframe")
            start_time = _parse_time(validation.get("prediction_timestamp"))
            if not symbol or not timeframe or not start_time:
                continue
            peak_due = validation.get("expected_peak_time") and validation.get("expected_peak_time") <= now_iso
            pullback_due = validation.get("expected_pullback_time") and validation.get("expected_pullback_time") <= now_iso
            end_raw = validation.get("expected_pullback_time") if pullback_due else validation.get("expected_peak_time")
            end_time = _parse_time(end_raw)
            if not end_time:
                continue
            candles = [
                row async for row in self.db.market_data.find(
                    {"symbol": symbol, "interval": timeframe, "timestamp": {"$gt": _iso(start_time), "$lte": _iso(end_time)}}
                ).sort([("timestamp", 1)]).limit(1000)
            ]
            if not candles:
                continue
            result = _continuous_lifecycle_result(validation, candles, peak_due, pullback_due)
            await self.db.prediction_lifecycle_validations.update_one({"_id": validation["_id"]}, {"$set": result})
            updated += 1
        return updated

    async def store_prediction_reality_stats(self) -> int:
        rows = [row async for row in self.db.prediction_lifecycle_validations.find({"status": "completed"})]
        await self.db.prediction_reality_stats.delete_many({"scope": {"$in": ["overall_latest", "symbol_latest", "timeframe_latest", "regime_latest", "confidence_bucket_latest"]}})
        created = 0
        scopes: list[tuple[str, str, list[dict]]] = [("overall_latest", "system", rows)]
        for field, scope in (("symbol", "symbol_latest"), ("timeframe", "timeframe_latest"), ("market_regime", "regime_latest")):
            grouped = defaultdict(list)
            for row in rows:
                grouped[str(row.get(field) or "UNKNOWN")].append(row)
            scopes.extend((scope, key, grouped_rows) for key, grouped_rows in grouped.items())
        confidence_groups = defaultdict(list)
        for row in rows:
            confidence_groups[_confidence_bucket(float(row.get("confidence") or 0))].append(row)
        scopes.extend(("confidence_bucket_latest", key, grouped_rows) for key, grouped_rows in confidence_groups.items())
        for scope, key, scoped in scopes:
            doc = {"scope": scope, "key": key, **_reality_metrics(scoped), "created_at": now_utc()}
            await self.db.prediction_reality_stats.insert_one(doc)
            created += 1
        return created

    async def store_adaptive_learning_stats(self) -> int:
        rows = [row async for row in self.db.prediction_lifecycle_validations.find({"source_type": "live", "status": "completed"})]
        validations = await self._prediction_validations("live")
        latest_scopes = [
            "learning_overall_latest",
            "confidence_bucket_learning_latest",
            "coin_learning_latest",
            "timeframe_learning_latest",
            "coin_timeframe_learning_latest",
            "target_learning_latest",
            "peak_learning_latest",
            "pullback_learning_latest",
            "timing_learning_latest",
            "style_learning_latest",
            "regime_learning_latest",
        ]
        await self.db.adaptive_learning_stats.delete_many({"scope": {"$in": latest_scopes}})
        created = 0
        groups: list[tuple[str, str, list[dict]]] = [("learning_overall_latest", "system", rows)]
        for field, scope in (
            ("symbol", "coin_learning_latest"),
            ("timeframe", "timeframe_learning_latest"),
            ("trading_style", "style_learning_latest"),
            ("market_regime", "regime_learning_latest"),
        ):
            grouped = defaultdict(list)
            for row in rows:
                key = _style_from_prediction(row) if field == "trading_style" and not row.get(field) else str(row.get(field) or "UNKNOWN")
                grouped[str(key)].append(row)
            groups.extend((scope, key, scoped) for key, scoped in grouped.items())
        coin_timeframes = defaultdict(list)
        for row in rows:
            coin_timeframes[f"{row.get('symbol') or 'UNKNOWN'}:{row.get('timeframe') or 'UNKNOWN'}"].append(row)
        groups.extend(("coin_timeframe_learning_latest", key, scoped) for key, scoped in coin_timeframes.items())

        confidence_groups = defaultdict(list)
        for row in validations:
            confidence_groups[_confidence_bucket(float(row.get("confidence") or 0))].append(row)
        for bucket, scoped in confidence_groups.items():
            doc = {
                "scope": "confidence_bucket_learning_latest",
                "key": bucket,
                **_confidence_learning_metrics(scoped),
                "created_at": now_utc(),
            }
            await self.db.adaptive_learning_stats.insert_one(doc)
            created += 1

        for scope, key, scoped in groups:
            doc = {"scope": scope, "key": key, **_adaptive_metrics(scoped), "created_at": now_utc()}
            await self.db.adaptive_learning_stats.insert_one(doc)
            created += 1

        for scope, key, metrics in (
            ("target_learning_latest", "system", _target_learning_metrics(rows)),
            ("peak_learning_latest", "system", _peak_learning_metrics(rows)),
            ("pullback_learning_latest", "system", _pullback_learning_metrics(rows)),
            ("timing_learning_latest", "system", _timing_learning_metrics(rows)),
        ):
            await self.db.adaptive_learning_stats.insert_one({"scope": scope, "key": key, **metrics, "created_at": now_utc()})
            created += 1
        return created

    async def update_dynamic_model_weights(self) -> dict:
        validations = await self._prediction_validations("live")
        lifecycle = [row async for row in self.db.prediction_lifecycle_validations.find({"source_type": "live", "status": "completed"})]
        grouped = defaultdict(list)
        for row in validations:
            grouped[str(row.get("model") or "rule_engine")].append(row)
        lifecycle_by_timeframe = defaultdict(list)
        for row in lifecycle:
            lifecycle_by_timeframe[str(row.get("timeframe") or "UNKNOWN")].append(row)
        model_scores = {}
        for model, rows in grouped.items():
            accuracy = _rate([row.get("direction_correct") for row in rows])
            timing = _avg(lifecycle_by_timeframe.get(str(rows[0].get("timeframe") or "UNKNOWN"), []), "timing_accuracy") if rows else 0
            drawdown_control = max(0, 100 - abs(_avg(lifecycle, "actual_drawdown_pct", "actual_drawdown")) * 8)
            profit_factor = max(0, min(100, _profit_factor([_return_percent(row.get("current_price"), row.get("actual_price")) for row in rows]) * 25))
            score = accuracy * 0.35 + profit_factor * 0.25 + timing * 0.20 + drawdown_control * 0.20
            model_scores[model] = round(max(1, score), 4)
        if not model_scores:
            model_scores = {"rule_engine": 1}
        weights = _normalize_weights(model_scores)
        doc = {
            "scope": "live",
            "weights": weights,
            "scores": model_scores,
            "model_count": len(model_scores),
            "sample_size": len(validations),
            "formula": "accuracy*0.35 + profit_factor*0.25 + timing_accuracy*0.20 + drawdown_control*0.20",
            "created_at": now_utc(),
        }
        await self.db.dynamic_model_weights.insert_one(doc)
        return doc

    async def store_alphaforge_score(self) -> dict:
        learning = await self.latest_adaptive_learning()
        overall = learning.get("overall") or {}
        previous = await self.db.alphaforge_scores.find_one({"scope": "latest"}, sort=[("created_at", -1)]) or {}
        if previous:
            overall = {**overall, "previous_alphaforge_score": previous.get("alphaforge_score")}
        score_doc = _alphaforge_score(overall, learning)
        await self.db.alphaforge_scores.insert_one(score_doc)
        return score_doc

    async def store_opportunity_discovery(self) -> dict:
        stats = await self.latest_reality_stats()
        learning = await self.latest_adaptive_learning()
        rows = await MongoRepository(self.db, "opportunities").find_many(limit=200, sort=[("rank", 1), ("overall_opportunity_score", -1)])
        rows = await self._ensure_core_opportunity_rows(rows)
        actionable = []
        rejected = []
        processed = []
        for row in rows:
            decision = _opportunity_filter(row, stats)
            aging = _opportunity_aging(row)
            row = {**row, **decision, **aging}
            row["validated_opportunity_score"] = round(_validated_opportunity_score(row, stats) * aging["signal_decay"], 4)
            row["opportunity_score_v3"] = round(_opportunity_score_v3(row, stats, learning) * aging["signal_decay"], 4)
            row["alphaforge_score"] = (learning.get("alphaforge_score") or {}).get("alphaforge_score")
            row["profitability_score"] = _lookup_learning(learning.get("coins", []), row.get("symbol"), "avg_return", default=0)
            row["timing_accuracy"] = _lookup_learning(learning.get("timeframes", []), row.get("timeframe"), "timing_accuracy", default=(learning.get("timing") or {}).get("timing_reliability_score", 50))
            row["peak_accuracy"] = (learning.get("peak") or {}).get("peak_accuracy_score")
            row["allocation_confidence"] = row["opportunity_score_v3"]
            row["mission_control"] = _mission_control(row)
            processed.append(row)
            if decision["is_actionable"]:
                actionable.append(row)
            else:
                rejected.append(row)
        ranked = sorted(actionable, key=lambda row: float(row.get("opportunity_score_v3") or row.get("validated_opportunity_score") or 0), reverse=True)
        core_rows = [row for row in ranked if row.get("symbol") in CORE_ASSETS]
        discovery_rows = [row for row in ranked if row.get("symbol") not in CORE_ASSETS]
        visible = _unique_by_symbol(core_rows + discovery_rows)
        allocation = _portfolio_allocation(visible, learning)
        payload = {
            "scope": "latest",
            "core_assets": core_rows,
            "discovery_assets": discovery_rows,
            "visible_opportunities": visible,
            "top_opportunity": visible[0] if visible else None,
            "top_3": visible[:3],
            "top_5": visible[:5],
            "top_buy": [row for row in visible if str(row.get("recommended_action") or "").upper() in {"BUY NOW", "BUY AGAIN", "WAIT"}][:5],
            "top_sell": [row for row in visible if str(row.get("recommended_action") or "").upper() in {"SELL", "TAKE PROFIT"}][:5],
            "top_reentry": [row for row in visible if str(row.get("recommended_action") or "").upper() == "BUY AGAIN" or float(row.get("reentry_score") or 0) >= 55][:5],
            "portfolio_allocation": allocation,
            "leaderboards": stats.get("leaderboards", {}),
            "adaptive_learning": learning,
            "actionable_count": len(actionable),
            "rejected_count": len(rejected),
            "created_at": now_utc(),
        }
        await self.db.opportunity_discovery.insert_one(payload)
        for row in processed:
            await self.db.alpha_discovery.insert_one({
                "symbol": row.get("symbol"),
                "asset_group": row.get("asset_group"),
                "setup_type": row.get("setup_type"),
                "setup_strength": row.get("setup_strength"),
                "discovery_score": row.get("discovery_score"),
                "alpha_score": row.get("alpha_score"),
                "is_actionable": row.get("is_actionable"),
                "filter_reasons": row.get("filter_reasons", []),
                "filter_bypass": row.get("filter_bypass"),
                "opportunity_age_hours": row.get("opportunity_age_hours"),
                "signal_decay": row.get("signal_decay"),
                "confidence_decay": row.get("confidence_decay"),
                "validated_opportunity_score": row.get("validated_opportunity_score"),
                "opportunity_score_v3": row.get("opportunity_score_v3"),
                "mission_control": row.get("mission_control"),
                "created_at": now_utc(),
            })
        return payload

    async def _ensure_core_opportunity_rows(self, rows: list[dict]) -> list[dict]:
        seen = {row.get("symbol") for row in rows}
        for symbol in CORE_ASSETS - seen:
            doc = await self.db.opportunities.find_one({"symbol": symbol})
            if doc:
                rows.append(_clean(doc))
        return rows

    async def latest_reality_stats(self) -> dict:
        overall = await self.db.prediction_reality_stats.find_one({"scope": "overall_latest", "key": "system"}, sort=[("created_at", -1)]) or {}
        symbols = [row async for row in self.db.prediction_reality_stats.find({"scope": "symbol_latest"}).sort([("average_return", -1)])]
        timeframes = [row async for row in self.db.prediction_reality_stats.find({"scope": "timeframe_latest"}).sort([("average_return", -1)])]
        regimes = [row async for row in self.db.prediction_reality_stats.find({"scope": "regime_latest"}).sort([("average_return", -1)])]
        confidence = [row async for row in self.db.prediction_reality_stats.find({"scope": "confidence_bucket_latest"}).sort([("key", 1)])]
        return {
            "overall": _clean(overall) if overall else {},
            "best_coin": _clean(symbols[0]) if symbols else None,
            "worst_coin": _clean(symbols[-1]) if symbols else None,
            "best_timeframe": _clean(timeframes[0]) if timeframes else None,
            "worst_timeframe": _clean(timeframes[-1]) if timeframes else None,
            "best_market_regime": _clean(regimes[0]) if regimes else None,
            "worst_market_regime": _clean(regimes[-1]) if regimes else None,
            "best_confidence_bucket": _clean(max(confidence, key=lambda row: float(row.get("success_rate") or 0), default={})) if confidence else None,
            "worst_confidence_bucket": _clean(min(confidence, key=lambda row: float(row.get("success_rate") or 0), default={})) if confidence else None,
            "confidence_buckets": [_clean(row) for row in confidence],
            "leaderboards": await self._leaderboards(),
        }

    async def latest_adaptive_learning(self) -> dict:
        scopes = {
            "overall": ("learning_overall_latest", "system"),
            "target": ("target_learning_latest", "system"),
            "peak": ("peak_learning_latest", "system"),
            "pullback": ("pullback_learning_latest", "system"),
            "timing": ("timing_learning_latest", "system"),
        }
        result = {}
        for key, (scope, item_key) in scopes.items():
            row = await self.db.adaptive_learning_stats.find_one({"scope": scope, "key": item_key}, sort=[("created_at", -1)]) or {}
            result[key] = _clean(row) if row else {}
        for key, scope in (
            ("coins", "coin_learning_latest"),
            ("timeframes", "timeframe_learning_latest"),
            ("coin_timeframes", "coin_timeframe_learning_latest"),
            ("styles", "style_learning_latest"),
            ("regimes", "regime_learning_latest"),
            ("confidence_buckets", "confidence_bucket_learning_latest"),
        ):
            result[key] = [_clean(row) async for row in self.db.adaptive_learning_stats.find({"scope": scope}).sort([("created_at", -1), ("learning_score", -1)]).limit(100)]
        result["dynamic_model_weights"] = _clean(await self.db.dynamic_model_weights.find_one({"scope": "live"}, sort=[("created_at", -1)]) or {})
        result["alphaforge_score"] = _clean(await self.db.alphaforge_scores.find_one({"scope": "latest"}, sort=[("created_at", -1)]) or {})
        return result

    async def _leaderboards(self) -> dict:
        rows = [row async for row in self.db.prediction_lifecycle_validations.find({"status": "completed"})]
        return {
            "best_coin_today": _best_by_window(rows, "symbol", timedelta(days=1)),
            "best_coin_week": _best_by_window(rows, "symbol", timedelta(days=7)),
            "best_coin_month": _best_by_window(rows, "symbol", timedelta(days=30)),
            "worst_coin": _worst(rows, "symbol"),
            "best_timeframe": _best(rows, "timeframe"),
            "worst_timeframe": _worst(rows, "timeframe"),
            "best_trading_style": _best(rows, "trading_style"),
            "best_market_regime": _best(rows, "market_regime"),
            "best_confidence_bucket": _best_confidence_bucket(rows),
            "most_reliable_coin": _best(rows, "symbol"),
            "most_profitable_coin": _best(rows, "symbol"),
        }

    async def ensure_simulated_trades(self) -> int:
        created = 0
        async for signal in self.db.signals.find({}):
            created += await self.ensure_simulated_trade(signal)
        return int(created)

    async def ensure_simulated_trade(self, signal: dict) -> int:
        signal_id = str(signal.get("id") or signal.get("_id"))
        action = str(signal.get("action") or signal.get("signal") or "").upper()
        decision = signal.get("decision") or {}
        if action not in {"BUY", "SELL"}:
            return 0
        entry = _optional_float(signal.get("entry") or decision.get("entry_price"))
        target = _optional_float(signal.get("target") or decision.get("take_profit_1"))
        stop = _optional_float(signal.get("stop_loss") or decision.get("stop_loss"))
        if not signal_id or not entry or not target or not stop:
            return 0
        doc = {
            "signal_id": signal_id,
            "symbol": signal.get("symbol"),
            "timeframe": signal.get("timeframe") or "1h",
            "source_type": "live",
            "status": "open",
            "signal_type": action,
            "entry_time": signal.get("created_at"),
            "entry_price": entry,
            "target_price": target,
            "stop_price": stop,
            "confidence": float(signal.get("confidence") or decision.get("confidence_score") or 0),
            "opportunity_score": float(signal.get("score") or 0),
            "risk_reward": str(signal.get("risk_reward") or decision.get("risk_reward_ratio") or ""),
            "signal": _clean(signal),
            "created_at": now_utc(),
            "updated_at": now_utc(),
        }
        result = await self.db.simulated_trades.update_one({"signal_id": signal_id}, {"$setOnInsert": doc}, upsert=True)
        return int(result.upserted_id is not None)

    async def evaluate_simulated_trades(self) -> int:
        evaluated = 0
        async for trade in self.db.simulated_trades.find({"status": "open"}):
            entry_time = _parse_time(trade.get("entry_time"))
            if not entry_time:
                continue
            candles = [
                row async for row in self.db.market_data.find(
                    {"symbol": trade.get("symbol"), "interval": trade.get("timeframe", "1h"), "timestamp": {"$gt": _iso(entry_time)}}
                ).sort([("timestamp", 1)]).limit(500)
            ]
            if not candles:
                continue
            result = _simulate_trade(trade, candles)
            if result["status"] != "completed":
                await self.db.simulated_trades.update_one({"_id": trade["_id"]}, {"$set": result})
                continue
            await self.db.simulated_trades.update_one({"_id": trade["_id"]}, {"$set": result})
            evaluated += 1
        return evaluated

    async def store_performance_snapshots(self) -> int:
        created = 0
        for window, days in WINDOWS.items():
            since = now_utc() - timedelta(days=days)
            validations = await self._prediction_validations("live", since)
            trades = await self._completed_trades("live", since)
            for scope, key, rows in _scopes(validations, "symbol", "timeframe", "model"):
                snapshot = {
                    "source_type": "live",
                    "window": window,
                    "scope": scope,
                    "key": key,
                    "prediction_metrics": _prediction_metrics(rows),
                    "trade_metrics": _trade_metrics(_matching_trades(trades, scope, key)),
                    "created_at": now_utc(),
                }
                await self.db.performance_snapshots.insert_one(snapshot)
                created += 1
        return created

    async def store_opportunity_score_validation(self) -> int:
        trades = await self._completed_trades("live")
        created = 0
        for low, high, bucket in SCORE_BUCKETS:
            rows = [row for row in trades if low <= float(row.get("opportunity_score", 0)) <= high]
            doc = {"source_type": "live", "bucket": bucket, **_trade_metrics(rows), "created_at": now_utc()}
            await self.db.opportunity_score_validations.insert_one(doc)
            created += 1
        return created

    async def store_confidence_calibration(self) -> int:
        validations = await self._prediction_validations("live")
        created = 0
        for low, high, bucket in CONFIDENCE_BUCKETS:
            rows = [row for row in validations if low <= float(row.get("confidence", 0)) <= high]
            actual = _rate([row.get("direction_correct") for row in rows])
            expected = mean([float(row.get("confidence", 0)) for row in rows]) if rows else 0
            doc = {
                "source_type": "live",
                "bucket": bucket,
                "sample_size": len(rows),
                "expected_confidence": round(expected, 2),
                "actual_success_rate": round(actual, 2),
                "calibration_error": round(abs(expected - actual), 2) if rows else 0,
                "confidence_reliability": round(max(0, 100 - abs(expected - actual)), 2) if rows else 0,
                "created_at": now_utc(),
            }
            await self.db.confidence_calibration.insert_one(doc)
            created += 1
        return created

    async def store_model_tournament(self) -> int:
        rows = await MongoRepository(self.db, "ml_model_results").find_many({"status": "trained"}, limit=1000, sort=[("created_at", -1)])
        latest = {}
        for row in rows:
            latest.setdefault((row.get("model"), row.get("timeframe")), row)
        ranked = []
        for row in latest.values():
            metrics = row.get("metrics", {})
            score = (
                float(metrics.get("accuracy", 0)) * 0.25
                + float(metrics.get("win_rate", 0)) * 0.25
                + min(100, float(metrics.get("profit_factor", 0)) * 25) * 0.25
                + max(0, min(100, 50 + float(metrics.get("sharpe_ratio", 0)) * 25)) * 0.25
            )
            ranked.append({"row": row, "score": score})
        ranked.sort(key=lambda item: item["score"], reverse=True)
        best = ranked[0]["row"] if ranked else None
        worst = ranked[-1]["row"] if ranked else None
        created = 0
        for item in ranked:
            row = item["row"]
            metrics = row.get("metrics", {})
            doc = {
                "source_type": "live",
                "model": row.get("model"),
                "timeframe": row.get("timeframe"),
                "accuracy": float(metrics.get("accuracy", 0)),
                "mae": float(metrics.get("mae", 0) or 0),
                "mape": float(metrics.get("mape", 0) or 0),
                "rmse": float(metrics.get("rmse", 0) or 0),
                "profit_factor": float(metrics.get("profit_factor", 0)),
                "sharpe": float(metrics.get("sharpe_ratio", 0)),
                "win_rate": float(metrics.get("win_rate", 0)),
                "performance_score": round(item["score"], 4),
                "is_best": best and row.get("model") == best.get("model") and row.get("timeframe") == best.get("timeframe"),
                "is_worst": worst and row.get("model") == worst.get("model") and row.get("timeframe") == worst.get("timeframe"),
                "created_at": now_utc(),
            }
            await self.db.model_tournament.insert_one(doc)
            created += 1
        return created

    async def evaluate_model_performance(self) -> dict:
        rows = await self._prediction_validations("live")
        lifecycle = [row async for row in self.db.prediction_lifecycle_validations.find({"source_type": "live", "status": "evaluated"})]
        direction_accuracy = _rate([row.get("direction_correct") for row in rows])
        peak_accuracy = mean([float(row.get("peak_accuracy", 0)) for row in lifecycle]) if lifecycle else 0
        profitability_accuracy = mean([float(row.get("profitability_accuracy", 0)) for row in lifecycle]) if lifecycle else 0
        return {
            "direction_accuracy": round(direction_accuracy, 4),
            "peak_accuracy": round(peak_accuracy, 4),
            "profitability_accuracy": round(profitability_accuracy, 4),
            "sample_size": len(rows),
            "lifecycle_sample_size": len(lifecycle),
        }

    async def update_lifecycle_model_weights(self) -> dict:
        performance = await self.evaluate_model_performance()
        model_weight = 0.40
        historical_weight = 0.25
        pattern_weight = 0.15
        regime_weight = 0.10
        data_weight = 0.10
        if performance["peak_accuracy"] > performance["direction_accuracy"]:
            pattern_weight += 0.03
            model_weight -= 0.03
        elif performance["direction_accuracy"] > 0:
            model_weight += 0.03
            pattern_weight -= 0.03
        weights = _normalize_weights({
            "model_confidence": model_weight,
            "historical_win_rate": historical_weight,
            "pattern_confidence": pattern_weight,
            "regime_reliability": regime_weight,
            "data_quality": data_weight,
        })
        doc = {"scope": "lifecycle_confidence", "weights": weights, "performance": performance, "created_at": now_utc()}
        await self.db.lifecycle_model_weights.insert_one(doc)
        return doc

    async def store_allocation_recommendations(self) -> dict:
        opportunities = await MongoRepository(self.db, "opportunities").find_many(limit=100, sort=[("rank", 1), ("alpha_score", -1)])
        performance = await self._completed_trades("live")
        perf_by_symbol = defaultdict(list)
        for trade in performance:
            perf_by_symbol[trade.get("symbol")].append(float(trade.get("pnl_percent", 0)))
        rows = []
        for row in opportunities[:8]:
            symbol = row.get("symbol")
            returns = perf_by_symbol.get(symbol, [])
            historical = (mean(returns) + 10) / 20 if returns else 0.5
            score = max(0, float(row.get("confidence", 0)) * 0.35 + float(row.get("expected_return", 0)) * 4 + float(row.get("alpha_score", 0)) * 0.25 + historical * 20)
            rows.append({"symbol": symbol, "score": score})
        total = sum(row["score"] for row in rows)
        allocations = []
        used = 0.0
        for row in rows:
            pct = round((row["score"] / total * 90) if total else 0, 2)
            used += pct
            allocations.append({"symbol": row["symbol"], "allocation_percent": pct})
        cash = round(max(0, 100 - used), 2)
        doc = {"allocations": allocations + [{"symbol": "CASH", "allocation_percent": cash}], "created_at": now_utc()}
        await self.db.allocation_recommendations.insert_one(doc)
        return doc

    async def dashboard(self) -> dict:
        latest = await self.db.performance_snapshots.find_one({"source_type": "live", "scope": "overall", "window": "30d"}, sort=[("created_at", -1)])
        return {
            "live_performance": _clean(latest) if latest else None,
            "windows": await MongoRepository(self.db, "performance_snapshots").find_many({"source_type": "live", "scope": "overall"}, limit=10, sort=[("created_at", -1)]),
            "opportunity_score_validation": await MongoRepository(self.db, "opportunity_score_validations").find_many({"source_type": "live"}, limit=10, sort=[("created_at", -1)]),
            "confidence_calibration": await MongoRepository(self.db, "confidence_calibration").find_many({"source_type": "live"}, limit=10, sort=[("created_at", -1)]),
            "model_tournament": await MongoRepository(self.db, "model_tournament").find_many({"source_type": "live"}, limit=20, sort=[("performance_score", -1), ("created_at", -1)]),
            "allocation": await MongoRepository(self.db, "allocation_recommendations").find_many(limit=1, sort=[("created_at", -1)]),
            "lifecycle_validations": await MongoRepository(self.db, "prediction_lifecycle_validations").find_many({"source_type": "live", "status": "evaluated"}, limit=25, sort=[("evaluated_at", -1)]),
            "completed_lifecycle_validations": await MongoRepository(self.db, "prediction_lifecycle_validations").find_many({"source_type": "live", "status": "completed"}, limit=25, sort=[("completed_at", -1)]),
            "prediction_reality": await self.latest_reality_stats(),
            "adaptive_learning": await self.latest_adaptive_learning(),
            "opportunity_discovery": await MongoRepository(self.db, "opportunity_discovery").find_many({"scope": "latest"}, limit=1, sort=[("created_at", -1)]),
            "lifecycle_model_weights": await MongoRepository(self.db, "lifecycle_model_weights").find_many(limit=5, sort=[("created_at", -1)]),
            "dynamic_model_weights": await MongoRepository(self.db, "dynamic_model_weights").find_many({"scope": "live"}, limit=5, sort=[("created_at", -1)]),
            "alphaforge_scores": await MongoRepository(self.db, "alphaforge_scores").find_many({"scope": "latest"}, limit=5, sort=[("created_at", -1)]),
        }

    async def _prediction_validations(self, source_type: str, since: datetime | None = None) -> list[dict]:
        query = {"source_type": source_type, "status": "evaluated"}
        if since:
            query["evaluated_at"] = {"$gte": since}
        return [row async for row in self.db.prediction_validations.find(query)]

    async def _completed_trades(self, source_type: str, since: datetime | None = None) -> list[dict]:
        query = {"source_type": source_type, "status": "completed"}
        if since:
            query["exit_time"] = {"$gte": since}
        return [row async for row in self.db.simulated_trades.find(query)]

    async def _mirror_prediction_result(self, validation: dict, result: dict) -> None:
        prediction_id = validation.get("prediction_id")
        if not prediction_id:
            return
        existing = await self.db.prediction_results.find_one({"prediction_id": prediction_id})
        if existing:
            await self.db.prediction_results.update_one(
                {"prediction_id": prediction_id},
                {"$set": {"source_type": validation.get("source_type"), "absolute_error": result["absolute_error"], "absolute_percentage_error": result["percentage_error"], "predicted_price": validation.get("predicted_price")}},
            )
            return
        doc = {
            "prediction_id": prediction_id,
            "symbol": validation.get("symbol"),
            "timeframe": validation.get("timeframe"),
            "source_type": validation.get("source_type"),
            "predicted": validation.get("predicted_direction"),
            "actual": result.get("actual_direction"),
            "correct": result.get("direction_correct"),
            "confidence": validation.get("confidence"),
            "predicted_price": validation.get("predicted_price"),
            "source_timestamp": validation.get("prediction_timestamp"),
            "resolved_timestamp": result.get("resolved_timestamp"),
            "start_price": validation.get("current_price"),
            "end_price": result.get("actual_price"),
            "absolute_error": result.get("absolute_error"),
            "absolute_percentage_error": result.get("percentage_error"),
            "return_percent": _return_percent(validation.get("current_price"), result.get("actual_price")),
            "resolved_at": result.get("evaluated_at"),
            "created_at": now_utc(),
        }
        await self.db.prediction_results.insert_one(doc)


def _simulate_trade(trade: dict, candles: list[dict]) -> dict:
    side = str(trade.get("signal_type", "")).upper()
    entry = float(trade.get("entry_price") or 0)
    target = float(trade.get("target_price") or 0)
    stop = float(trade.get("stop_price") or 0)
    max_profit = 0.0
    max_drawdown = 0.0
    exit_price = float(candles[-1].get("close") or entry)
    exit_time = candles[-1].get("timestamp")
    reason = "open"
    target_hit = False
    stop_hit = False
    for candle in candles:
        high = float(candle.get("high") or 0)
        low = float(candle.get("low") or 0)
        favorable = ((high - entry) / entry * 100) if side == "BUY" else ((entry - low) / entry * 100)
        adverse = ((low - entry) / entry * 100) if side == "BUY" else ((entry - high) / entry * 100)
        max_profit = max(max_profit, favorable)
        max_drawdown = min(max_drawdown, adverse)
        if side == "BUY" and high >= target:
            exit_price, exit_time, reason, target_hit = target, candle.get("timestamp"), "target_hit", True
            break
        if side == "BUY" and low <= stop:
            exit_price, exit_time, reason, stop_hit = stop, candle.get("timestamp"), "stop_hit", True
            break
        if side == "SELL" and low <= target:
            exit_price, exit_time, reason, target_hit = target, candle.get("timestamp"), "target_hit", True
            break
        if side == "SELL" and high >= stop:
            exit_price, exit_time, reason, stop_hit = stop, candle.get("timestamp"), "stop_hit", True
            break
    if reason == "open":
        return {"status": "open", "max_profit": round(max_profit, 4), "max_drawdown": round(max_drawdown, 4), "updated_at": now_utc()}
    pnl = ((exit_price - entry) / entry * 100) if side == "BUY" else ((entry - exit_price) / entry * 100)
    holding = _holding_duration(trade.get("entry_time"), exit_time)
    return {
        "status": "completed",
        "exit_time": _parse_time(exit_time),
        "exit_price": exit_price,
        "max_profit": round(max_profit, 4),
        "max_drawdown": round(max_drawdown, 4),
        "target_hit": target_hit,
        "stop_hit": stop_hit,
        "holding_duration": holding,
        "pnl_percent": round(pnl, 4),
        "reason_for_exit": reason,
        "target_reached": target_hit,
        "stop_reached": stop_hit,
        "updated_at": now_utc(),
    }


def _lifecycle_result(validation: dict, candles: list[dict]) -> dict:
    current_price = float(validation.get("current_price") or 0)
    if current_price <= 0:
        return {"status": "evaluated", "updated_at": now_utc(), "evaluated_at": now_utc()}
    peak_candle = max(candles, key=lambda row: float(row.get("high") or 0))
    peak_index = candles.index(peak_candle)
    post_peak = candles[peak_index:] or candles
    pullback_candle = min(post_peak, key=lambda row: float(row.get("low") or 0))
    actual_peak_price = float(peak_candle.get("high") or current_price)
    actual_pullback_price = float(pullback_candle.get("low") or actual_peak_price)
    actual_close = float(candles[-1].get("close") or current_price)
    actual_return = _return_percent(current_price, actual_close)
    actual_drawdown = min(0, min((float(row.get("low") or current_price) / current_price - 1) * 100 for row in candles))
    expected_peak = _optional_float(validation.get("expected_peak_price"))
    expected_pullback = _optional_float(validation.get("expected_pullback_price"))
    expected_return = float(validation.get("expected_return") or 0)
    expected_drawdown = float(validation.get("expected_drawdown") or 0)
    peak_accuracy = _accuracy_from_error(expected_peak, actual_peak_price)
    pullback_accuracy = _accuracy_from_error(expected_pullback, actual_pullback_price)
    timing_accuracy = _timing_accuracy(validation.get("expected_peak_time"), peak_candle.get("timestamp"))
    profitability_accuracy = max(0, 100 - abs(expected_return - actual_return) * 8)
    drawdown_accuracy = max(0, 100 - abs(abs(expected_drawdown) - abs(actual_drawdown)) * 8)
    return {
        "status": "completed",
        "actual_peak_price": round(actual_peak_price, 8),
        "actual_peak_time": peak_candle.get("timestamp"),
        "actual_pullback_price": round(actual_pullback_price, 8),
        "actual_pullback_time": pullback_candle.get("timestamp"),
        "actual_return": round(actual_return, 4),
        "actual_drawdown": round(actual_drawdown, 4),
        "peak_accuracy": round(peak_accuracy, 4),
        "timing_accuracy": round(timing_accuracy, 4),
        "pullback_accuracy": round(pullback_accuracy, 4),
        "profitability_accuracy": round(profitability_accuracy, 4),
        "drawdown_accuracy": round(drawdown_accuracy, 4),
        "evaluated_at": now_utc(),
        "updated_at": now_utc(),
    }


def _continuous_lifecycle_result(validation: dict, candles: list[dict], peak_due: bool, pullback_due: bool) -> dict:
    current_price = float(validation.get("current_price") or 0)
    if current_price <= 0:
        return {"updated_at": now_utc()}
    result: dict[str, Any] = {"updated_at": now_utc()}
    peak_candle = max(candles, key=lambda row: float(row.get("high") or 0))
    peak_price = float(peak_candle.get("high") or current_price)
    if peak_due and not validation.get("peak_completed"):
        expected_peak = _optional_float(validation.get("expected_peak_price"))
        result.update({
            "actual_peak_price": round(peak_price, 8),
            "actual_peak_time": peak_candle.get("timestamp"),
            "peak_accuracy_pct": round(_accuracy_from_error(expected_peak, peak_price), 4),
            "peak_accuracy": round(_accuracy_from_error(expected_peak, peak_price), 4),
            "peak_accuracy_score": round(_accuracy_from_error(expected_peak, peak_price), 4),
            "peak_price_error_pct": round(_signed_error_pct(expected_peak, peak_price), 4) if expected_peak else None,
            "peak_timing_error_minutes": _timing_error_minutes(validation.get("expected_peak_time"), peak_candle.get("timestamp")),
            "peak_completed": True,
            "status": "peak_evaluated",
        })
    target_stop = _target_stop_result(validation, candles)
    result.update(target_stop)
    if pullback_due:
        peak_index = candles.index(peak_candle)
        post_peak = candles[peak_index:] or candles
        pullback_candle = min(post_peak, key=lambda row: float(row.get("low") or 0))
        actual_pullback = float(pullback_candle.get("low") or peak_price)
        actual_close = float(candles[-1].get("close") or current_price)
        actual_return = _return_percent(current_price, actual_close)
        actual_drawdown = min(0, min((float(row.get("low") or current_price) / current_price - 1) * 100 for row in candles))
        expected_pullback = _optional_float(validation.get("expected_pullback_price"))
        expected_return = float(validation.get("expected_return") or 0)
        result.update({
            "actual_pullback_price": round(actual_pullback, 8),
            "actual_pullback_time": pullback_candle.get("timestamp"),
            "pullback_accuracy_pct": round(_accuracy_from_error(expected_pullback, actual_pullback), 4),
            "pullback_accuracy": round(_accuracy_from_error(expected_pullback, actual_pullback), 4),
            "pullback_accuracy_score": round(_accuracy_from_error(expected_pullback, actual_pullback), 4),
            "pullback_price_error_pct": round(_signed_error_pct(expected_pullback, actual_pullback), 4) if expected_pullback else None,
            "pullback_timing_error_minutes": _timing_error_minutes(validation.get("expected_pullback_time"), pullback_candle.get("timestamp")),
            "actual_return_pct": round(actual_return, 4),
            "actual_return": round(actual_return, 4),
            "actual_drawdown_pct": round(actual_drawdown, 4),
            "actual_drawdown": round(actual_drawdown, 4),
            "actual_holding_duration": _holding_duration(validation.get("prediction_timestamp"), candles[-1].get("timestamp")),
            "expected_vs_actual_return": round(actual_return - expected_return, 4),
            "profitability_accuracy": round(max(0, 100 - abs(expected_return - actual_return) * 8), 4),
            "timing_accuracy": round(max(0, 100 - abs(_timing_error_minutes(validation.get("expected_peak_time"), result.get("actual_peak_time") or peak_candle.get("timestamp"))) / 60 * 4), 4),
            "pullback_completed": True,
            "status": "completed",
            "completed_at": now_utc(),
            "evaluated_at": now_utc(),
        })
    return result


def _target_stop_result(validation: dict, candles: list[dict]) -> dict:
    side = "BUY" if float(validation.get("expected_return") or 0) >= 0 else "SELL"
    levels = {
        "target1": _optional_float(validation.get("target_1")),
        "target2": _optional_float(validation.get("target_2")),
        "target3": _optional_float(validation.get("target_3") or validation.get("expected_peak_price")),
        "stop_loss": _optional_float(validation.get("stop_loss")),
    }
    result: dict[str, Any] = {}
    for name in ("target1", "target2", "target3"):
        level = levels[name]
        success_key = f"{name}_success"
        time_key = f"{name}_time"
        if level is None or validation.get(success_key):
            continue
        hit = _level_hit(candles, level, side, target=True)
        result[success_key] = bool(hit)
        if hit:
            result[time_key] = hit
    stop = levels["stop_loss"]
    if stop is not None and not validation.get("stop_loss_hit"):
        hit = _level_hit(candles, stop, side, target=False)
        result["stop_loss_hit"] = bool(hit)
        if hit:
            result["stop_loss_time"] = hit
    return result


def _prediction_metrics(rows: list[dict]) -> dict:
    total = len(rows)
    correct = len([row for row in rows if row.get("direction_correct")])
    absolute = [float(row.get("absolute_error", 0)) for row in rows if row.get("absolute_error") is not None]
    percentage = [float(row.get("percentage_error", 0)) for row in rows if row.get("percentage_error") is not None]
    squared = [value * value for value in absolute]
    return {
        "sample_size": total,
        "accuracy": round(correct / total * 100, 2) if total else 0,
        "mae": round(mean(absolute), 6) if absolute else 0,
        "mape": round(mean(percentage), 6) if percentage else 0,
        "rmse": round(math.sqrt(mean(squared)), 6) if squared else 0,
    }


def _trade_metrics(rows: list[dict]) -> dict:
    returns = [float(row.get("pnl_percent", 0)) for row in rows]
    wins = [value for value in returns if value > 0]
    losses = [abs(value) for value in returns if value < 0]
    max_drawdown = _max_drawdown(returns)
    profit = sum(wins)
    loss = sum(losses)
    return {
        "sample_size": len(rows),
        "win_rate": round(len(wins) / len(returns) * 100, 2) if returns else 0,
        "loss_rate": round(len(losses) / len(returns) * 100, 2) if returns else 0,
        "average_winner": round(mean(wins), 6) if wins else 0,
        "average_loser": round(mean(losses), 6) if losses else 0,
        "profit_factor": round(profit / loss, 4) if loss else round(profit, 4) if profit else 0,
        "expectancy": round(mean(returns), 6) if returns else 0,
        "sharpe_ratio": _sharpe(returns),
        "maximum_drawdown": max_drawdown,
        "recovery_factor": round(sum(returns) / abs(max_drawdown), 4) if max_drawdown else 0,
    }


def _scopes(rows: list[dict], *fields: str):
    yield "overall", "system", rows
    for field in fields:
        groups = defaultdict(list)
        for row in rows:
            groups[row.get(field) or "UNKNOWN"].append(row)
        for key, grouped in groups.items():
            yield field, key, grouped


def _matching_trades(trades: list[dict], scope: str, key: str) -> list[dict]:
    if scope == "overall":
        return trades
    field = "signal_type" if scope == "signal_type" else scope
    return [row for row in trades if str(row.get(field) or "UNKNOWN") == str(key)]


def _actual_direction(start: float, end: float) -> str:
    if start <= 0:
        return "SIDEWAYS"
    change = end / start - 1
    if change > 0.003:
        return "UP"
    if change < -0.003:
        return "DOWN"
    return "SIDEWAYS"


def _price_errors(predicted: Any, actual: float) -> dict:
    if predicted is None or actual <= 0:
        return {"absolute_error": None, "percentage_error": None}
    absolute = abs(float(predicted) - actual)
    return {"absolute_error": round(absolute, 8), "percentage_error": round(absolute / actual * 100, 8)}


def _optional_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _holding_duration(start: Any, end: Any) -> str:
    start_time = _parse_time(start)
    end_time = _parse_time(end)
    if not start_time or not end_time:
        return ""
    hours = (end_time - start_time).total_seconds() / 3600
    return f"{round(hours, 2)}h"


def _return_percent(start: Any, end: Any) -> float:
    start_number = _optional_float(start)
    end_number = _optional_float(end)
    if not start_number or end_number is None:
        return 0
    return round((end_number / start_number - 1) * 100, 4)


def _rate(values: list[Any]) -> float:
    if not values:
        return 0
    return len([value for value in values if value]) / len(values) * 100


def _reality_metrics(rows: list[dict]) -> dict:
    total = len(rows)
    target1 = _rate([row.get("target1_success") for row in rows])
    target2 = _rate([row.get("target2_success") for row in rows])
    target3 = _rate([row.get("target3_success") for row in rows])
    stop = _rate([row.get("stop_loss_hit") for row in rows])
    returns = [float(row.get("actual_return_pct", row.get("actual_return", 0)) or 0) for row in rows]
    drawdowns = [float(row.get("actual_drawdown_pct", row.get("actual_drawdown", 0)) or 0) for row in rows]
    success = [row.get("target1_success") and not row.get("stop_loss_hit") for row in rows]
    holding_hours = [_duration_hours(row.get("actual_holding_duration")) for row in rows if row.get("actual_holding_duration")]
    return {
        "completed_predictions": total,
        "pending_predictions": 0,
        "peak_accuracy": _avg(rows, "peak_accuracy_pct", "peak_accuracy"),
        "pullback_accuracy": _avg(rows, "pullback_accuracy_pct", "pullback_accuracy"),
        "time_accuracy": _avg(rows, "timing_accuracy"),
        "target1_hit_rate": round(target1, 4),
        "target2_hit_rate": round(target2, 4),
        "target3_hit_rate": round(target3, 4),
        "stop_loss_rate": round(stop, 4),
        "average_return": round(mean(returns), 4) if returns else 0,
        "average_drawdown": round(mean(drawdowns), 4) if drawdowns else 0,
        "average_holding_duration_hours": round(mean(holding_hours), 4) if holding_hours else 0,
        "success_rate": round(_rate(success), 4),
        "sample_size": total,
    }


def _confidence_learning_metrics(rows: list[dict]) -> dict:
    returns = [_return_percent(row.get("current_price"), row.get("actual_price")) for row in rows]
    wins = [row for row in rows if row.get("direction_correct")]
    losses = [row for row in rows if not row.get("direction_correct")]
    expected = mean([float(row.get("confidence", 0)) for row in rows]) if rows else 0
    actual = _rate([row.get("direction_correct") for row in rows])
    avg_return = mean(returns) if returns else 0
    reliability = max(0, 100 - abs(expected - actual)) if rows else 0
    profitability = max(0, min(100, 50 + avg_return * 10))
    return {
        "predictions": len(rows),
        "wins": len(wins),
        "losses": len(losses),
        "avg_return": round(avg_return, 4),
        "avg_drawdown": 0,
        "displayed_confidence": round(expected, 4),
        "actual_success_rate": round(actual, 4),
        "confidence_bucket_accuracy": round(actual, 4),
        "confidence_bucket_profitability": round(profitability, 4),
        "confidence_reliability_score": round(reliability, 4),
        "learning_score": round(reliability * 0.65 + profitability * 0.35, 4),
        "sample_size": len(rows),
    }


def _adaptive_metrics(rows: list[dict]) -> dict:
    returns = [float(row.get("actual_return_pct", row.get("actual_return", 0)) or 0) for row in rows]
    drawdowns = [float(row.get("actual_drawdown_pct", row.get("actual_drawdown", 0)) or 0) for row in rows]
    success = [row.get("target1_success") and not row.get("stop_loss_hit") for row in rows]
    wins = [value for value in returns if value > 0]
    losses = [abs(value) for value in returns if value < 0]
    profit_factor = round(sum(wins) / sum(losses), 4) if losses else round(sum(wins), 4) if wins else 0
    target_hit = _rate([row.get("target1_success") or row.get("target2_success") or row.get("target3_success") for row in rows])
    timing = _avg(rows, "timing_accuracy")
    peak = _avg(rows, "peak_accuracy_score", "peak_accuracy_pct", "peak_accuracy")
    drawdown_control = max(0, 100 - abs(mean(drawdowns) if drawdowns else 0) * 8)
    profitability = max(0, min(100, 50 + (mean(returns) if returns else 0) * 10))
    learning_score = _bounded(
        _rate(success) * 0.22
        + profitability * 0.18
        + min(100, profit_factor * 25) * 0.15
        + target_hit * 0.15
        + timing * 0.12
        + peak * 0.10
        + drawdown_control * 0.08
    )
    return {
        "predictions": len(rows),
        "wins": len([value for value in returns if value > 0]),
        "losses": len([value for value in returns if value <= 0]),
        "accuracy": round(_rate(success), 4),
        "profit_factor": profit_factor,
        "avg_return": round(mean(returns), 4) if returns else 0,
        "avg_drawdown": round(mean(drawdowns), 4) if drawdowns else 0,
        "target_hit_rate": round(target_hit, 4),
        "timing_accuracy": round(timing, 4),
        "peak_accuracy": round(peak, 4),
        "drawdown_control": round(drawdown_control, 4),
        "learning_score": round(learning_score, 4),
        "coin_learning_score": round(learning_score, 4),
        "timeframe_reliability_score": round(learning_score, 4),
        "style_reliability_score": round(learning_score, 4),
        "sample_size": len(rows),
    }


def _target_learning_metrics(rows: list[dict]) -> dict:
    holding_hours = [_duration_hours(row.get("actual_holding_duration")) for row in rows if row.get("actual_holding_duration")]
    metrics = {
        "target1_hit_rate": round(_rate([row.get("target1_success") for row in rows]), 4),
        "target2_hit_rate": round(_rate([row.get("target2_success") for row in rows]), 4),
        "target3_hit_rate": round(_rate([row.get("target3_success") for row in rows]), 4),
        "stop_loss_rate": round(_rate([row.get("stop_loss_hit") for row in rows]), 4),
        "average_holding_duration_hours": round(mean(holding_hours), 4) if holding_hours else 0,
        "average_drawdown": _avg(rows, "actual_drawdown_pct", "actual_drawdown"),
        "sample_size": len(rows),
    }
    metrics["target_reliability_score"] = round(_bounded(metrics["target1_hit_rate"] * 0.35 + metrics["target2_hit_rate"] * 0.25 + metrics["target3_hit_rate"] * 0.20 + max(0, 100 - metrics["stop_loss_rate"]) * 0.20), 4)
    return metrics


def _peak_learning_metrics(rows: list[dict]) -> dict:
    errors = [abs(float(row.get("peak_price_error_pct") or 0)) for row in rows if row.get("peak_price_error_pct") is not None]
    timing = [abs(float(row.get("peak_timing_error_minutes") or 0)) for row in rows if row.get("peak_timing_error_minutes") is not None]
    return {
        "peak_price_error_pct": round(mean(errors), 4) if errors else 0,
        "peak_timing_error_minutes": round(mean(timing), 4) if timing else 0,
        "peak_accuracy_score": _avg(rows, "peak_accuracy_score", "peak_accuracy_pct", "peak_accuracy"),
        "sample_size": len(rows),
    }


def _pullback_learning_metrics(rows: list[dict]) -> dict:
    errors = [abs(float(row.get("pullback_price_error_pct") or 0)) for row in rows if row.get("pullback_price_error_pct") is not None]
    timing = [abs(float(row.get("pullback_timing_error_minutes") or 0)) for row in rows if row.get("pullback_timing_error_minutes") is not None]
    return {
        "pullback_price_error_pct": round(mean(errors), 4) if errors else 0,
        "pullback_timing_error_minutes": round(mean(timing), 4) if timing else 0,
        "pullback_accuracy_score": _avg(rows, "pullback_accuracy_score", "pullback_accuracy_pct", "pullback_accuracy"),
        "sample_size": len(rows),
    }


def _timing_learning_metrics(rows: list[dict]) -> dict:
    timing_errors = []
    for row in rows:
        if row.get("peak_timing_error_minutes") is not None:
            timing_errors.append(abs(float(row.get("peak_timing_error_minutes") or 0)))
        if row.get("pullback_timing_error_minutes") is not None:
            timing_errors.append(abs(float(row.get("pullback_timing_error_minutes") or 0)))
    average_error = mean(timing_errors) if timing_errors else 0
    median_error = sorted(timing_errors)[len(timing_errors) // 2] if timing_errors else 0
    reliability = max(0, 100 - average_error / 60 * 4)
    return {
        "average_timing_error_minutes": round(average_error, 4),
        "median_timing_error_minutes": round(median_error, 4),
        "timing_reliability_score": round(reliability, 4),
        "sample_size": len(rows),
    }


def _opportunity_filter(row: dict, stats: dict) -> dict:
    symbol = str(row.get("symbol") or "")
    if symbol in CORE_ASSETS:
        return {"is_actionable": True, "filter_reasons": [], "calibrated_confidence": _calibrated_confidence(float(row.get("calibrated_confidence") or row.get("confidence") or 0), stats), "filter_bypass": "core_asset"}
    expected_return = float(row.get("expected_return") or row.get("profit_potential") or 0)
    confidence = float(row.get("calibrated_confidence") or row.get("confidence") or 0)
    rr = float(row.get("risk_reward_value") or _risk_reward_from_text(row.get("risk_reward_ratio")) or 0)
    volume_strength = float(row.get("volume_strength") or row.get("components", {}).get("volume_strength") or 60)
    invalid = str(row.get("recommended_action") or "").upper() in {"SELL"} and expected_return > 0
    reasons = []
    if expected_return <= 1:
        reasons.append("expected_return_below_1pct")
    if rr <= 1.5:
        reasons.append("risk_reward_below_1_5")
    if confidence <= 55:
        reasons.append("confidence_below_55")
    if volume_strength <= 20:
        reasons.append("volume_too_weak")
    if invalid:
        reasons.append("active_invalidation_signal")
    return {
        "is_actionable": not reasons,
        "filter_reasons": reasons,
        "calibrated_confidence": _calibrated_confidence(confidence, stats),
        "filter_bypass": None,
    }


def _validated_opportunity_score(row: dict, stats: dict) -> float:
    expected = abs(float(row.get("expected_return") or row.get("profit_potential") or 0)) * 10
    confidence = float(row.get("calibrated_confidence") or row.get("confidence") or 0)
    win_rate = float(row.get("historical_win_rate") or 50)
    rr = min(100, float(row.get("risk_reward_value") or _risk_reward_from_text(row.get("risk_reward_ratio")) or 0) * 25)
    validation = float((stats.get("overall") or {}).get("success_rate") or 50)
    return max(0, min(100, expected * 0.25 + confidence * 0.25 + win_rate * 0.2 + rr * 0.15 + validation * 0.15))


def _opportunity_score_v3(row: dict, stats: dict, learning: dict) -> float:
    expected = min(100, abs(float(row.get("expected_return") or row.get("profit_potential") or 0)) * 10)
    confidence = float(row.get("calibrated_confidence") or row.get("confidence") or 0)
    win_rate = float(row.get("historical_win_rate") or 50)
    profitability = _lookup_learning(learning.get("coins", []), row.get("symbol"), "avg_return", default=0)
    profitability_score = max(0, min(100, 50 + profitability * 10))
    rr = min(100, float(row.get("risk_reward_value") or _risk_reward_from_text(row.get("risk_reward_ratio")) or 0) * 25)
    target = float((learning.get("target") or {}).get("target_reliability_score") or 50)
    peak = float((learning.get("peak") or {}).get("peak_accuracy_score") or 50)
    timing = float((learning.get("timing") or {}).get("timing_reliability_score") or 50)
    volume = float(row.get("volume_strength") or 50)
    regime = _lookup_learning(learning.get("regimes", []), row.get("market_regime"), "learning_score", default=float(row.get("market_regime_score") or 50))
    style = _lookup_learning(learning.get("styles", []), row.get("setup_type") or row.get("trading_style"), "learning_score", default=float(row.get("pattern_confidence") or 50))
    validation = float((stats.get("overall") or {}).get("success_rate") or 50)
    return _bounded(
        expected * 0.13
        + confidence * 0.13
        + win_rate * 0.10
        + profitability_score * 0.10
        + rr * 0.10
        + target * 0.10
        + peak * 0.08
        + timing * 0.08
        + volume * 0.06
        + regime * 0.05
        + style * 0.04
        + validation * 0.03
    )


def _opportunity_aging(row: dict) -> dict:
    timestamp = _parse_time(row.get("updated_at") or row.get("created_at")) or now_utc()
    age_hours = max(0, (now_utc() - timestamp).total_seconds() / 3600)
    signal_decay = max(0.35, 1 - age_hours / 48)
    confidence_decay = max(0.45, 1 - age_hours / 72)
    return {
        "opportunity_age_hours": round(age_hours, 4),
        "opportunity_age": _duration_from_hours(age_hours),
        "signal_decay": round(signal_decay, 4),
        "confidence_decay": round(confidence_decay, 4),
    }


def _portfolio_allocation(rows: list[dict], learning: dict | None = None) -> dict:
    learning = learning or {}
    qualified = rows[:8]
    scores = []
    for row in qualified:
        reliability = _lookup_learning(learning.get("coins", []), row.get("symbol"), "learning_score", default=50)
        risk_control = max(0, 100 - abs(float(row.get("expected_drawdown") or 0)) * 8)
        score = float(row.get("opportunity_score_v3") or row.get("validated_opportunity_score") or row.get("alpha_score") or 0)
        scores.append(max(0, score * 0.65 + reliability * 0.25 + risk_control * 0.10))
    total = sum(scores)
    allocations = []
    expected_return = 0.0
    expected_drawdown = 0.0
    for row, score in zip(qualified, scores):
        pct = round(score / total * 90, 2) if total else 0
        allocations.append({
            "symbol": row.get("symbol"),
            "suggested_allocation_percent": pct,
            "recommended_allocation": pct,
            "allocation_confidence": round(min(100, score), 4),
            "expected_return": row.get("expected_return"),
            "expected_drawdown": row.get("expected_drawdown"),
            "portfolio_risk_score": row.get("risk_score"),
        })
        expected_return += pct / 100 * float(row.get("expected_return") or 0)
        expected_drawdown += pct / 100 * abs(float(row.get("expected_drawdown") or 0))
    cash = round(max(0, 100 - sum(row["suggested_allocation_percent"] for row in allocations)), 2)
    return {
        "allocations": allocations + [{"symbol": "CASH", "suggested_allocation_percent": cash, "recommended_allocation": cash}],
        "expected_portfolio_return": round(expected_return, 4),
        "expected_portfolio_drawdown": round(expected_drawdown, 4),
        "portfolio_risk_score": round(min(100, expected_drawdown * 8), 2),
    }


def _mission_control(row: dict) -> dict:
    score = float(row.get("opportunity_score_v3") or row.get("validated_opportunity_score") or 0)
    return {
        "action": row.get("recommended_action"),
        "alphaforge_score": row.get("alphaforge_score"),
        "prediction_accuracy": row.get("historical_win_rate"),
        "profitability_score": row.get("profitability_score"),
        "timing_accuracy": row.get("timing_accuracy"),
        "confidence_reliability": row.get("calibrated_confidence") or row.get("confidence"),
        "peak_accuracy": row.get("peak_accuracy"),
        "opportunity_quality": round(score, 4),
        "portfolio_intelligence": row.get("allocation_confidence"),
        "quality_trend": "Improving" if score >= 65 else "Stable" if score >= 40 else "Declining",
        "entry": row.get("entry_price"),
        "expected_peak": row.get("expected_peak_price"),
        "expected_peak_date": row.get("expected_peak_time"),
        "expected_profit": row.get("profit_potential") or row.get("expected_return"),
        "probability": row.get("calibrated_confidence") or row.get("confidence"),
        "sell_at": row.get("sell_price") or row.get("target_3") or row.get("expected_peak_price"),
        "expected_pullback": row.get("expected_pullback_price"),
        "expected_rebuy_date": row.get("expected_pullback_time"),
        "expected_drawdown": row.get("expected_drawdown"),
        "risk": row.get("risk_classification") or row.get("risk_score"),
        "holding_duration": row.get("holding_duration"),
    }


def _unique_by_symbol(rows: list[dict]) -> list[dict]:
    seen = set()
    unique = []
    for row in rows:
        symbol = row.get("symbol")
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        unique.append(row)
    return unique


def _calibrated_confidence(confidence: float, stats: dict) -> float:
    buckets = stats.get("confidence_buckets") or []
    bucket = _confidence_bucket(confidence)
    match = next((row for row in buckets if row.get("key") == bucket), None)
    if not match or not match.get("sample_size"):
        return round(max(1, min(95, confidence)), 2)
    success = float(match.get("success_rate") or confidence)
    adjusted = confidence * 0.65 + success * 0.35
    return round(max(1, min(95, adjusted)), 2)


def _confidence_bucket(confidence: float) -> str:
    if confidence >= 90:
        return "90-95"
    for low, high, label in CONFIDENCE_BUCKETS:
        if low <= confidence <= high:
            return label
    return "below 50"


def _lookup_learning(rows: list[dict], key: Any, field: str, default: Any = 50) -> float:
    text = str(key or "UNKNOWN")
    match = next((row for row in rows if str(row.get("key") or "") == text), None)
    if not match:
        return float(default or 0)
    return float(match.get(field) if match.get(field) is not None else default or 0)


def _alphaforge_score(overall: dict, learning: dict) -> dict:
    prediction_accuracy = float(overall.get("accuracy") or overall.get("success_rate") or 0)
    profitability = max(0, min(100, 50 + float(overall.get("avg_return", overall.get("average_return", 0)) or 0) * 10))
    target_success = float((learning.get("target") or {}).get("target_reliability_score") or overall.get("target1_hit_rate") or 0)
    peak_accuracy = float((learning.get("peak") or {}).get("peak_accuracy_score") or overall.get("peak_accuracy") or 0)
    timing_accuracy = float((learning.get("timing") or {}).get("timing_reliability_score") or overall.get("time_accuracy") or 0)
    confidence_rows = learning.get("confidence_buckets") or []
    confidence_calibration = mean([float(row.get("confidence_reliability_score") or 0) for row in confidence_rows]) if confidence_rows else 0
    risk_control = max(0, 100 - abs(float(overall.get("avg_drawdown", overall.get("average_drawdown", 0)) or 0)) * 8)
    components = {
        "prediction_accuracy": round(prediction_accuracy, 4),
        "profitability": round(profitability, 4),
        "target_success": round(target_success, 4),
        "peak_accuracy": round(peak_accuracy, 4),
        "timing_accuracy": round(timing_accuracy, 4),
        "confidence_calibration": round(confidence_calibration, 4),
        "risk_control": round(risk_control, 4),
    }
    usable = [max(1, value) for value in components.values()]
    product = 1.0
    for value in usable:
        product *= value / 100
    score = (product ** (1 / len(usable))) * 100 if usable else 0
    previous = None
    trend = "Stable"
    if overall.get("previous_alphaforge_score") is not None:
        previous = float(overall.get("previous_alphaforge_score") or 0)
        trend = "Improving" if score > previous + 1 else "Declining" if score < previous - 1 else "Stable"
    return {
        "scope": "latest",
        "alphaforge_score": round(_bounded(score), 4),
        "components": components,
        "formula": "geometric_mean(prediction_accuracy, profitability, target_success, peak_accuracy, timing_accuracy, confidence_calibration, risk_control)",
        "trend": trend,
        "previous_score": previous,
        "created_at": now_utc(),
    }


def _duration_from_hours(hours: float) -> str:
    if hours < 1:
        return f"{round(hours * 60)}m"
    if hours < 24:
        return f"{round(hours, 1)}h"
    return f"{round(hours / 24, 1)}d"


def _best_by_window(rows: list[dict], field: str, window: timedelta) -> dict | None:
    since = now_utc() - window
    scoped = [row for row in rows if (_parse_time(row.get("completed_at") or row.get("evaluated_at") or row.get("created_at")) or now_utc()) >= since]
    return _best(scoped, field)


def _best(rows: list[dict], field: str) -> dict | None:
    ranked = _rank_group(rows, field)
    return ranked[0] if ranked else None


def _worst(rows: list[dict], field: str) -> dict | None:
    ranked = _rank_group(rows, field)
    return ranked[-1] if ranked else None


def _rank_group(rows: list[dict], field: str) -> list[dict]:
    grouped = defaultdict(list)
    for row in rows:
        grouped[str(row.get(field) or "UNKNOWN")].append(row)
    ranked = []
    for key, scoped in grouped.items():
        returns = [float(row.get("actual_return_pct", row.get("actual_return", 0)) or 0) for row in scoped]
        ranked.append({"key": key, "average_return": round(mean(returns), 4) if returns else 0, "sample_size": len(scoped), "success_rate": _rate([row.get("target1_success") and not row.get("stop_loss_hit") for row in scoped])})
    return sorted(ranked, key=lambda row: (row["average_return"], row["success_rate"], row["sample_size"]), reverse=True)


def _best_confidence_bucket(rows: list[dict]) -> dict | None:
    for row in rows:
        row["confidence_bucket"] = _confidence_bucket(float(row.get("confidence") or 0))
    return _best(rows, "confidence_bucket")


def _avg(rows: list[dict], *keys: str) -> float:
    values = []
    for row in rows:
        for key in keys:
            if row.get(key) is not None:
                values.append(float(row.get(key) or 0))
                break
    return round(mean(values), 4) if values else 0


def _level_hit(candles: list[dict], level: float, side: str, target: bool) -> str | None:
    for candle in candles:
        high = float(candle.get("high") or 0)
        low = float(candle.get("low") or 0)
        if side == "BUY":
            hit = high >= level if target else low <= level
        else:
            hit = low <= level if target else high >= level
        if hit:
            return candle.get("timestamp")
    return None


def _signed_error_pct(expected: float | None, actual: float) -> float:
    if expected is None or actual <= 0:
        return 0
    return (expected - actual) / actual * 100


def _timing_error_minutes(expected: Any, actual: Any) -> float:
    expected_time = _parse_time(expected)
    actual_time = _parse_time(actual)
    if not expected_time or not actual_time:
        return 0
    return round((actual_time - expected_time).total_seconds() / 60, 4)


def _duration_hours(value: Any) -> float:
    text = str(value or "").strip().lower()
    token = text.split()[0] if text else ""
    token = token.replace("hours", "").replace("hour", "").replace("hrs", "").replace("hr", "").replace("h", "").replace("days", "").replace("day", "").replace("d", "")
    number = _optional_float(token)
    if number is None:
        return 0
    return number * 24 if "d" in text else number


def _profit_factor(returns: list[float]) -> float:
    wins = [value for value in returns if value > 0]
    losses = [abs(value) for value in returns if value < 0]
    if losses:
        return round(sum(wins) / sum(losses), 4)
    return round(sum(wins), 4) if wins else 0


def _bounded(value: float) -> float:
    return max(0, min(100, float(value or 0)))


def _style_from_prediction(prediction: dict) -> str:
    action = str(prediction.get("recommended_action") or "").upper()
    regime = str(prediction.get("market_regime") or "")
    expected = float(prediction.get("predicted_return_pct") or prediction.get("expected_return") or 0)
    volume = float(prediction.get("volume_strength") or 0)
    if volume >= 70:
        return "Range Expansion"
    if action == "BUY AGAIN":
        return "Pullback"
    if "Bullish" in regime and expected > 0:
        return "Trend Continuation"
    if "Bearish" in regime and expected > 0:
        return "Reversal"
    if expected < 0:
        return "Distribution"
    return "Breakout" if expected > 1 else "Accumulation"


def _risk_reward_from_text(value: Any) -> float:
    text = str(value or "")
    if ":" in text:
        try:
            return float(text.split(":")[-1])
        except ValueError:
            return 0
    return _optional_float(value) or 0


def _sharpe(values: list[float]) -> float:
    if len(values) < 2:
        return 0
    deviation = pstdev(values)
    return round(mean(values) / deviation, 4) if deviation else 0


def _max_drawdown(values: list[float]) -> float:
    peak = 0.0
    equity = 0.0
    drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = min(drawdown, equity - peak)
    return round(drawdown, 6)


def _accuracy_from_error(expected: float | None, actual: float) -> float:
    if expected is None or actual <= 0:
        return 0
    return max(0, 100 - abs(expected - actual) / actual * 100)


def _timing_accuracy(expected: Any, actual: Any) -> float:
    expected_time = _parse_time(expected)
    actual_time = _parse_time(actual)
    if not expected_time or not actual_time:
        return 0
    hours = abs((expected_time - actual_time).total_seconds()) / 3600
    return max(0, 100 - hours * 4)


def _normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    total = sum(max(0, value) for value in weights.values()) or 1
    return {key: round(max(0, value) / total, 4) for key, value in weights.items()}


def _clean(document: dict) -> dict:
    item = dict(document)
    item.pop("_id", None)
    for key, value in list(item.items()):
        if isinstance(value, ObjectId):
            item[key] = str(value)
    return item
