import math
from collections import defaultdict
from datetime import datetime
from statistics import mean, pstdev
from time import perf_counter
from typing import Any

from app.core.config import SUPPORTED_SYMBOLS
from app.repositories.base import MongoRepository, now_utc
from app.services.notifications import TelegramNotifier


FORECAST_HORIZONS = ("24h", "48h", "7d")
MODEL_VERSION = "phase8-ensemble-v1"


class IntelligenceService:
    def __init__(self, db):
        self.db = db

    async def refresh_all(self, symbols: list[str] | None = None) -> dict:
        started = perf_counter()
        run = await self._job_started("forecast_intelligence")
        try:
            symbols = [item.upper() for item in (symbols or list(SUPPORTED_SYMBOLS)) if item.upper() in SUPPORTED_SYMBOLS]
            forecasts = []
            alpha_scores = []
            regimes = []
            opportunities = []
            monitoring = []
            for symbol in symbols:
                context = await self._context(symbol)
                if not context:
                    continue
                regime = self._market_regime(context)
                alpha = self._alpha_score(context, regime)
                forecast = self._forecast(context, alpha, regime)
                opportunity = self._opportunity(context, forecast, alpha, regime)
                monitor = await self._ml_monitoring(symbol)

                await self._upsert("market_regimes", {"symbol": symbol}, regime)
                await self._upsert("alpha_scores", {"symbol": symbol}, alpha)
                await self._upsert("forecasts", {"symbol": symbol}, forecast)
                await self._upsert("opportunities", {"symbol": symbol}, opportunity)
                await self._upsert("ml_monitoring", {"symbol": symbol}, monitor)
                await self._maybe_alert(symbol, forecast, alpha, opportunity)

                regimes.append(regime)
                alpha_scores.append(alpha)
                forecasts.append(forecast)
                opportunities.append(opportunity)
                monitoring.append(monitor)

            ranked_opportunities = await self._ranked_opportunities()
            for index, row in enumerate(ranked_opportunities, 1):
                row["rank"] = index
                await self.db.opportunities.update_one({"symbol": row["symbol"]}, {"$set": {"rank": index, "updated_at": now_utc()}})
                await self.db.alpha_scores.update_one({"symbol": row["symbol"]}, {"$set": {"rank": index, "updated_at": now_utc()}})
            if set(symbols) == set(SUPPORTED_SYMBOLS):
                await self._cleanup_rankings(symbols)

            duration = round((perf_counter() - started) * 1000, 2)
            await self._job_finished(run, "completed", duration, {"forecasts": len(forecasts), "opportunities": len(opportunities)})
            await self._system_health("forecast_jobs", "healthy", duration, None)
            return {
                "forecasts": len(forecasts),
                "alpha_scores": len(alpha_scores),
                "market_regimes": len(regimes),
                "opportunities": len(opportunities),
                "ml_monitoring": len(monitoring),
                "execution_time_ms": duration,
            }
        except Exception as exc:
            duration = round((perf_counter() - started) * 1000, 2)
            await self._job_finished(run, "failed", duration, {"error": str(exc)})
            await self._system_health("forecast_jobs", "failed", duration, str(exc))
            raise

    async def forecasts(self) -> list[dict]:
        rows = await MongoRepository(self.db, "forecasts").find_many(limit=200, sort=[("alpha_score", -1), ("confidence", -1)])
        if rows:
            return rows
        await self.refresh_all()
        return await MongoRepository(self.db, "forecasts").find_many(limit=200, sort=[("alpha_score", -1), ("confidence", -1)])

    async def forecast(self, symbol: str) -> dict | None:
        doc = await MongoRepository(self.db, "forecasts").find_one({"symbol": symbol.upper()})
        if doc:
            return doc
        await self.refresh_all([symbol])
        return await MongoRepository(self.db, "forecasts").find_one({"symbol": symbol.upper()})

    async def intelligence_dashboard(self) -> dict:
        forecasts = await self.forecasts()
        opportunities = await MongoRepository(self.db, "opportunities").find_many(limit=100, sort=[("rank", 1)])
        regimes = await MongoRepository(self.db, "market_regimes").find_many(limit=100, sort=[("confidence", -1)])
        models = await MongoRepository(self.db, "ml_model_results").find_many(limit=100, sort=[("created_at", -1)])
        analytics = _clean(await self.db.analytics_stats.find_one({"scope": "global"}, sort=[("created_at", -1)]))
        best_model = max(
            [row for row in models if row.get("status") == "trained"],
            key=lambda row: row.get("metrics", {}).get("f1", 0),
            default=None,
        )
        top_return = max(forecasts, key=lambda row: abs(float(row.get("expected_return", 0))), default=None)
        top_confidence = max(forecasts, key=lambda row: float(row.get("confidence", 0)), default=None)
        symbol_rows = await self._symbol_performance()
        return {
            "top_opportunity": opportunities[0] if opportunities else None,
            "top_opportunities": opportunities[:5],
            "market_regime_overview": regimes,
            "highest_confidence_forecast": top_confidence,
            "highest_expected_return": top_return,
            "most_accurate_model": best_model,
            "best_performing_coin": symbol_rows[0] if symbol_rows else None,
            "worst_performing_coin": symbol_rows[-1] if symbol_rows else None,
            "live_alpha_rankings": opportunities,
            "analytics_metrics": analytics.get("metrics", {}),
        }

    async def paper_trading_analytics(self, user_id: str) -> dict:
        trades = await MongoRepository(self.db, "paper_trades").find_many({"user_id": user_id}, limit=100000, sort=[("created_at", 1)])
        closed = [row for row in trades if row.get("side") == "CLOSE"]
        pnls = [float(row.get("pnl", 0)) for row in closed]
        wins = [value for value in pnls if value > 0]
        losses = [abs(value) for value in pnls if value < 0]
        by_symbol: dict[str, list[float]] = defaultdict(list)
        for row, pnl in zip(closed, pnls):
            by_symbol[str(row.get("symbol") or "UNKNOWN")].append(pnl)
        symbol_perf = [{"symbol": key, "pnl": round(sum(values), 2), "trades": len(values)} for key, values in by_symbol.items()]
        symbol_perf.sort(key=lambda row: row["pnl"], reverse=True)
        monthly = defaultdict(float)
        equity = 0.0
        curve = []
        for row, pnl in zip(closed, pnls):
            equity += pnl
            timestamp = str(row.get("created_at") or "")
            monthly[timestamp[:7] or "unknown"] += pnl
            curve.append({"timestamp": timestamp, "equity": round(equity, 2), "pnl": round(pnl, 2)})
        returns = self._returns(pnls)
        return {
            "win_rate": round(len(wins) / len(pnls) * 100, 2) if pnls else 0,
            "profit_factor": round(sum(wins) / sum(losses), 2) if losses else round(sum(wins), 2) if wins else 0,
            "sharpe_ratio": self._sharpe(returns),
            "sortino_ratio": self._sortino(returns),
            "max_drawdown": self._max_drawdown(pnls),
            "average_trade": round(mean(pnls), 2) if pnls else 0,
            "best_coin": symbol_perf[0] if symbol_perf else None,
            "worst_coin": symbol_perf[-1] if symbol_perf else None,
            "monthly_return": [{"month": key, "pnl": round(value, 2)} for key, value in sorted(monthly.items())],
            "equity_curve": curve,
            "total_closed_trades": len(closed),
        }

    async def _context(self, symbol: str) -> dict | None:
        candles = [_clean(row) async for row in self.db.market_data.find({"symbol": symbol, "interval": "1h"}).sort([("timestamp", -1)]).limit(240)]
        candles.reverse()
        if len(candles) < 30:
            return None
        indicators = await self.db.indicator_data.find_one({"symbol": symbol, "interval": "1h"}, sort=[("timestamp", -1)]) or {}
        predictions = [
            _clean(row)
            async for row in self.db.predictions.find({"symbol": symbol, "bootstrap_evaluation": {"$ne": True}, "stale": {"$ne": True}})
            .sort([("prediction_timestamp", -1), ("updated_at", -1), ("created_at", -1)])
            .limit(20)
        ]
        ensemble = [_clean(row) async for row in self.db.ensemble_predictions.find({"symbol": symbol}).sort([("created_at", -1)]).limit(10)]
        signal = await self.db.signals.find_one({"symbol": symbol}, sort=[("created_at", -1)]) or {}
        sentiment = await self.db.market_sentiment.find_one(sort=[("created_at", -1)]) or {}
        ml = [_clean(row) async for row in self.db.ml_predictions.find({"symbol": symbol}).sort([("created_at", -1)]).limit(20)]
        return {
            "symbol": symbol,
            "candles": candles,
            "indicators": _clean(indicators),
            "predictions": predictions,
            "ensemble": ensemble,
            "signal": _clean(signal),
            "sentiment": _clean(sentiment),
            "ml": ml,
        }

    def _forecast(self, context: dict, alpha: dict, regime: dict) -> dict:
        candles = context["candles"]
        current_price = float(candles[-1]["close"])
        momentum_24h = self._window_return(candles, 24)
        momentum_48h = self._window_return(candles, 48)
        momentum_7d = self._window_return(candles, min(168, len(candles) - 1))
        prediction_moves = [float(row.get("predicted_return_pct", row.get("predicted_change_pct", 0))) for row in context["predictions"] if row.get("predicted_change_pct") is not None or row.get("predicted_return_pct") is not None]
        ml_bias = self._direction_bias(context["ml"] + context["ensemble"])
        rule_move = mean([momentum_24h, momentum_48h, momentum_7d])
        model_move = mean(prediction_moves) if prediction_moves else 0
        ensemble_move = rule_move * 0.35 + model_move * 0.4 + ml_bias * 0.25
        confidence = round(max(1, min(99, alpha["confidence"] * 0.65 + regime["confidence"] * 0.2 + abs(ensemble_move) * 1.5)), 2)
        move_24h = ensemble_move * 0.45 + momentum_24h * 0.35 + ml_bias * 0.2
        move_48h = ensemble_move * 0.7 + momentum_48h * 0.25 + ml_bias * 0.25
        move_7d = ensemble_move * 1.3 + momentum_7d * 0.45 + ml_bias * 0.35
        forecast_24h = self._price(current_price, move_24h)
        forecast_48h = self._price(current_price, move_48h)
        forecast_7d = self._price(current_price, move_7d)
        scenario_width = max(1.5, abs(move_7d) * 0.45 + (100 - confidence) * 0.04)
        expected_return = round((forecast_7d / current_price - 1) * 100, 4) if current_price else 0
        return {
            "symbol": context["symbol"],
            "current_price": round(current_price, 8),
            "forecast_24h": forecast_24h,
            "forecast_48h": forecast_48h,
            "forecast_7d": forecast_7d,
            "bull_case": self._price(current_price, move_7d + scenario_width),
            "base_case": forecast_7d,
            "bear_case": self._price(current_price, move_7d - scenario_width),
            "confidence": confidence,
            "alpha_score": alpha["alpha_score"],
            "market_regime": regime["regime"],
            "expected_return": expected_return,
            "generated_at": now_utc(),
            "model_version": MODEL_VERSION,
            "forecast_source": "ensemble",
            "components": {
                "rule_based_move": round(rule_move, 4),
                "prediction_move": round(model_move, 4),
                "ml_bias": round(ml_bias, 4),
            },
        }

    def _alpha_score(self, context: dict, regime: dict) -> dict:
        predictions = context["predictions"]
        ml_rows = context["ml"] + context["ensemble"]
        indicators = context["indicators"]
        signal = context["signal"]
        prediction_quality = mean([float(row.get("confidence_score", row.get("confidence", 0))) for row in predictions[:4]]) if predictions else 0
        ml_confidence = mean([float(row.get("probability", row.get("confidence", 0))) for row in ml_rows[:6]]) if ml_rows else prediction_quality
        trend_strength = float(indicators.get("adx") or indicators.get("trend_score") or 50)
        volume_strength = max(0, min(100, float(indicators.get("volume_ratio", 1)) * 35))
        momentum = max(0, min(100, 50 + self._window_return(context["candles"], 24) * 6))
        risk_reward = self._risk_reward_score(signal)
        regime_fit = regime["confidence"]
        score = (
            prediction_quality * 0.25
            + ml_confidence * 0.20
            + trend_strength * 0.15
            + volume_strength * 0.10
            + momentum * 0.10
            + risk_reward * 0.10
            + regime_fit * 0.10
        )
        confidence = round(max(1, min(99, mean([prediction_quality or 50, ml_confidence or 50, regime_fit]))), 2)
        return {
            "symbol": context["symbol"],
            "alpha_score": round(max(0, min(100, score)), 2),
            "confidence": confidence,
            "rank": 0,
            "components": {
                "prediction_quality": round(prediction_quality, 2),
                "ml_confidence": round(ml_confidence, 2),
                "trend_strength": round(trend_strength, 2),
                "volume_strength": round(volume_strength, 2),
                "momentum": round(momentum, 2),
                "risk_reward": round(risk_reward, 2),
                "market_regime_fit": round(regime_fit, 2),
            },
            "created_at": now_utc(),
        }

    def _market_regime(self, context: dict) -> dict:
        indicators = context["indicators"]
        candles = context["candles"]
        ema20 = float(indicators.get("ema20") or candles[-1]["close"])
        ema50 = float(indicators.get("ema50") or candles[-1]["close"])
        ema200 = float(indicators.get("ema200") or candles[-1]["close"])
        adx = float(indicators.get("adx") or 20)
        atr = float(indicators.get("atr") or 0)
        close = float(candles[-1]["close"])
        volume_ratio = float(indicators.get("volume_ratio") or 1)
        volatility = (atr / close * 100) if close else 0
        if ema20 > ema50 > ema200 and adx >= 28:
            regime = "Strong Bullish"
        elif ema20 > ema50 and adx >= 18:
            regime = "Bullish"
        elif ema20 < ema50 < ema200 and adx >= 28:
            regime = "Strong Bearish"
        elif ema20 < ema50 and adx >= 18:
            regime = "Bearish"
        elif volatility < 1.2:
            regime = "Range"
        else:
            regime = "Neutral"
        confidence = round(max(1, min(99, adx * 1.6 + min(30, volume_ratio * 10) + min(25, volatility * 4))), 2)
        return {
            "symbol": context["symbol"],
            "regime": regime,
            "confidence": confidence,
            "inputs": {"ema20": ema20, "ema50": ema50, "ema200": ema200, "adx": adx, "atr": atr, "volatility": round(volatility, 4), "volume_ratio": volume_ratio},
            "created_at": now_utc(),
        }

    def _opportunity(self, context: dict, forecast: dict, alpha: dict, regime: dict) -> dict:
        prediction = context["predictions"][0] if context["predictions"] else {}
        expected_return = float(forecast.get("expected_return", 0))
        risk_score = round(max(1, min(100, 100 - alpha["components"]["risk_reward"] + abs(expected_return) * 1.5)), 2)
        recommended_action = prediction.get("recommended_action") or ("BUY NOW" if expected_return > 1 else "SELL" if expected_return < -1 else "WAIT")
        action_confidence = float(prediction.get("action_confidence") or prediction.get("confidence_score") or alpha["confidence"])
        setup = self._setup(context, prediction, regime, expected_return)
        validation_success = float(prediction.get("historical_win_rate") or 50)
        rr = float(prediction.get("risk_reward_value") or _risk_reward_number(prediction.get("risk_reward_ratio")) or 0)
        alpha_score = self._alpha_score_v2(
            expected_return=float(prediction.get("predicted_return_pct", expected_return)),
            confidence=float(prediction.get("calibrated_confidence", prediction.get("confidence_score", alpha["confidence"]))),
            historical_win_rate=float(prediction.get("historical_win_rate") or 50),
            risk_reward=rr,
            regime_score=float(prediction.get("market_regime_score") or 50),
            volume_strength=float(alpha["components"].get("volume_strength") or 0),
            similarity=float(prediction.get("similarity_score") or 50),
            validation_success=validation_success,
        )
        return {
            "symbol": context["symbol"],
            "asset_group": "CORE" if context["symbol"] in {"BTC_INR", "BDX_INR"} else "DISCOVERY",
            "alpha_score": alpha_score,
            "expected_return": round(float(prediction.get("predicted_return_pct", expected_return)), 4),
            "confidence": float(prediction.get("calibrated_confidence", prediction.get("confidence_score", alpha["confidence"]))),
            "calibrated_confidence": float(prediction.get("calibrated_confidence", prediction.get("confidence_score", alpha["confidence"]))),
            "risk_score": float(prediction.get("risk_score", risk_score)),
            "rank": 0,
            "market_regime": prediction.get("market_regime") or regime["regime"],
            "forecast_24h": forecast["forecast_24h"],
            "forecast_48h": forecast["forecast_48h"],
            "forecast_7d": forecast["forecast_7d"],
            "recommended_action": recommended_action,
            "action_confidence": action_confidence,
            "action_reason": self._action_reason(recommended_action, prediction, expected_return),
            "action_priority": self._action_priority(recommended_action, prediction, expected_return),
            "setup_type": setup["setup_type"],
            "setup_strength": setup["setup_strength"],
            "discovery_score": setup["discovery_score"],
            "volume_strength": float(alpha["components"].get("volume_strength") or 0),
            "validation_success_rate": validation_success,
            "entry_price": prediction.get("entry_price"),
            "entry_zone": prediction.get("entry_zone"),
            "stop_loss": prediction.get("stop_loss"),
            "target_1": prediction.get("target_1"),
            "target_2": prediction.get("target_2"),
            "target_3": prediction.get("target_3"),
            "expected_price": prediction.get("expected_price") or prediction.get("predicted_price"),
            "expected_peak_price": prediction.get("expected_peak_price"),
            "expected_peak_time": prediction.get("expected_peak_time"),
            "expected_pullback_price": prediction.get("expected_pullback_price"),
            "expected_pullback_time": prediction.get("expected_pullback_time"),
            "holding_duration": prediction.get("holding_duration"),
            "profit_potential": prediction.get("profit_potential"),
            "expected_drawdown": prediction.get("expected_drawdown"),
            "historical_win_rate": prediction.get("historical_win_rate"),
            "pattern_confidence": prediction.get("pattern_confidence"),
            "risk_reward_ratio": prediction.get("risk_reward_ratio"),
            "risk_reward_value": rr,
            "buy_score": prediction.get("buy_score"),
            "sell_score": prediction.get("sell_score"),
            "reentry_score": prediction.get("reentry_score"),
            "opportunity_score_v2": prediction.get("opportunity_score_v2"),
            "overall_opportunity_score": prediction.get("overall_opportunity_score"),
            "created_at": now_utc(),
        }

    async def _ml_monitoring(self, symbol: str) -> dict:
        rows = await MongoRepository(self.db, "ml_model_results").find_many(limit=100, sort=[("created_at", -1)])
        feature_rows = await MongoRepository(self.db, "ml_features").find_many({"symbol": symbol}, limit=20, sort=[("created_at", -1)])
        trained = [row for row in rows if row.get("status") == "trained"]
        latest = trained[0] if trained else {}
        accuracy = float(latest.get("metrics", {}).get("accuracy", 0) or 0)
        drift = "HIGH" if accuracy and accuracy < 35 else "MEDIUM" if accuracy and accuracy < 45 else "LOW"
        return {
            "symbol": symbol,
            "latest_model": latest.get("model"),
            "timeframe": latest.get("timeframe"),
            "accuracy": accuracy,
            "feature_importance": latest.get("feature_importance", [])[:20],
            "drift_status": drift,
            "performance_status": "degraded" if drift == "HIGH" else "stable",
            "retraining_recommended": drift in {"HIGH", "MEDIUM"},
            "feature_snapshots": len(feature_rows),
            "created_at": now_utc(),
        }

    async def _maybe_alert(self, symbol: str, forecast: dict, alpha: dict, opportunity: dict) -> None:
        old = await self.db.forecasts.find_one({"symbol": symbol})
        forecast_change = 0.0
        if old and old.get("forecast_48h"):
            forecast_change = abs((float(forecast["forecast_48h"]) / float(old["forecast_48h"]) - 1) * 100)
        signal = await self.db.signals.find_one({"symbol": symbol}, sort=[("created_at", -1)]) or {}
        if alpha["alpha_score"] > 90 or forecast_change > 5 or float(signal.get("confidence", 0)) > 85:
            await TelegramNotifier().send_alpha_alert({**forecast, **opportunity, "forecast_change": round(forecast_change, 2)})

    async def _symbol_performance(self) -> list[dict]:
        rows = await MongoRepository(self.db, "prediction_results").find_many(limit=100000, sort=[("resolved_at", -1)])
        grouped = defaultdict(lambda: {"total": 0, "correct": 0, "return": 0.0})
        for row in rows:
            symbol = row.get("symbol")
            if not symbol:
                continue
            grouped[symbol]["total"] += 1
            grouped[symbol]["correct"] += 1 if row.get("correct") else 0
            grouped[symbol]["return"] += float(row.get("return_percent", 0))
        table = []
        for symbol, value in grouped.items():
            table.append({
                "symbol": symbol,
                "accuracy": round(value["correct"] / value["total"] * 100, 2) if value["total"] else 0,
                "average_return": round(value["return"] / value["total"], 4) if value["total"] else 0,
                "total": value["total"],
            })
        return sorted(table, key=lambda row: (row["average_return"], row["accuracy"]), reverse=True)

    async def _upsert(self, collection: str, query: dict, document: dict) -> None:
        await self.db[collection].update_one(query, {"$set": {**document, "updated_at": now_utc()}, "$setOnInsert": {"first_created_at": now_utc()}}, upsert=True)

    async def _cleanup_rankings(self, symbols: list[str]) -> None:
        query = {"$or": [{"symbol": {"$exists": False}}, {"symbol": {"$nin": symbols}}, {"symbol": {"$in": ["", None]}}]}
        for collection in ("opportunities", "alpha_scores", "forecasts", "market_regimes", "ml_monitoring"):
            await self.db[collection].delete_many(query)

    async def _ranked_opportunities(self) -> list[dict]:
        rows = [
            _clean(row)
            async for row in self.db.opportunities.find({"symbol": {"$exists": True, "$nin": ["", None]}})
        ]
        return sorted(rows, key=lambda row: (float(row.get("overall_opportunity_score") or row.get("opportunity_score_v2") or row.get("alpha_score", 0)), float(row.get("expected_return", 0)), float(row.get("confidence", 0))), reverse=True)

    async def _job_started(self, job: str) -> dict:
        run = {"job": job, "status": "running", "started_at": now_utc(), "created_at": now_utc()}
        result = await self.db.job_runs.insert_one(run)
        run["_id"] = result.inserted_id
        return run

    async def _job_finished(self, run: dict, status: str, duration_ms: float, metadata: dict) -> None:
        await self.db.job_runs.update_one({"_id": run["_id"]}, {"$set": {"status": status, "duration_ms": duration_ms, "metadata": metadata, "finished_at": now_utc()}})

    async def _system_health(self, component: str, status: str, duration_ms: float, error: str | None) -> None:
        await self.db.system_health.update_one(
            {"component": component},
            {"$set": {"component": component, "status": status, "last_latency_ms": duration_ms, "last_error": error, "updated_at": now_utc()}, "$setOnInsert": {"created_at": now_utc()}},
            upsert=True,
        )

    def _window_return(self, candles: list[dict], window: int) -> float:
        if len(candles) <= window:
            return 0.0
        start = float(candles[-window - 1].get("close") or 0)
        end = float(candles[-1].get("close") or 0)
        return round(((end / start) - 1) * 100, 4) if start > 0 else 0.0

    def _direction_bias(self, rows: list[dict]) -> float:
        if not rows:
            return 0.0
        score = 0.0
        total = 0.0
        for row in rows:
            direction = str(row.get("prediction") or row.get("final_prediction") or row.get("action") or "").upper()
            confidence = float(row.get("probability") or row.get("confidence") or 50)
            if direction in {"UP", "BUY"}:
                score += confidence
                total += confidence
            elif direction in {"DOWN", "SELL"}:
                score -= confidence
                total += confidence
            else:
                total += confidence
        return round(score / total * 6, 4) if total else 0.0

    def _risk_reward_score(self, signal: dict) -> float:
        raw = str(signal.get("risk_reward") or signal.get("decision", {}).get("risk_reward_ratio") or "")
        parts = [float(item) for item in raw.replace(":", " ").replace("/", " ").split() if _is_number(item)]
        if len(parts) >= 2 and parts[0] > 0:
            return max(0, min(100, parts[1] / parts[0] * 35))
        return float(signal.get("score") or 50)

    def _price(self, current: float, move_pct: float) -> float:
        return round(current * (1 + move_pct / 100), 8)

    def _action_reason(self, action: str, prediction: dict, expected_return: float) -> str:
        if prediction.get("filter_reasons"):
            return ", ".join(prediction.get("filter_reasons", [])[:3])
        if action == "BUY NOW":
            return "Expected return, confidence, and risk/reward pass actionable thresholds"
        if action == "BUY AGAIN":
            return "Pullback/re-entry profile is favorable after the expected peak"
        if action in {"SELL", "TAKE PROFIT"}:
            return "Expected return or lifecycle risk favors reducing exposure"
        if action == "HOLD":
            return "Prediction edge is limited; maintain current exposure"
        return "Wait for better return, confidence, or risk/reward confirmation"

    def _action_priority(self, action: str, prediction: dict, expected_return: float) -> int:
        score = float(prediction.get("overall_opportunity_score") or prediction.get("opportunity_score_v2") or abs(expected_return) * 10)
        if action == "BUY NOW":
            score += 15
        if action in {"SELL", "TAKE PROFIT"}:
            score += 8
        return int(max(1, min(100, round(score))))

    def _setup(self, context: dict, prediction: dict, regime: dict, expected_return: float) -> dict:
        indicators = context["indicators"]
        volume_ratio = float(indicators.get("volume_ratio") or 1)
        volatility = float(indicators.get("volatility") or 0)
        trend = float(indicators.get("trend_strength") or 0)
        rsi = float(indicators.get("rsi") or 50)
        ema20 = float(indicators.get("ema20") or 0)
        ema50 = float(indicators.get("ema50") or 0)
        regime_name = str(prediction.get("market_regime") or regime.get("regime") or "")
        if volume_ratio >= 1.8 and volatility >= 1.5:
            setup_type = "Volume Spike"
        elif volatility >= 2.5:
            setup_type = "Volatility Expansion"
        elif ema20 > ema50 and trend > 0.5 and expected_return > 0:
            setup_type = "Trend Continuation"
        elif rsi < 38 and expected_return > 0:
            setup_type = "Pullback"
        elif rsi > 68 and expected_return < 0:
            setup_type = "Distribution"
        elif "Bearish" in regime_name and expected_return > 0:
            setup_type = "Trend Reversal"
        elif abs(trend) < 0.25 and volume_ratio >= 1.2:
            setup_type = "Accumulation"
        else:
            setup_type = "Breakout" if expected_return > 1 else "Neutral"
        strength = max(1, min(100, abs(expected_return) * 10 + volume_ratio * 18 + abs(trend) * 8 + volatility * 6))
        discovery = max(1, min(100, strength * 0.45 + float(prediction.get("pattern_confidence") or 50) * 0.25 + float(prediction.get("confidence_score") or 50) * 0.30))
        return {"setup_type": setup_type, "setup_strength": round(strength, 2), "discovery_score": round(discovery, 2)}

    def _alpha_score_v2(self, expected_return: float, confidence: float, historical_win_rate: float, risk_reward: float, regime_score: float, volume_strength: float, similarity: float, validation_success: float) -> float:
        score = (
            min(100, abs(expected_return) * 10) * 0.20
            + confidence * 0.20
            + historical_win_rate * 0.15
            + min(100, risk_reward * 25) * 0.15
            + regime_score * 0.10
            + min(100, volume_strength) * 0.08
            + similarity * 0.07
            + validation_success * 0.05
        )
        return round(max(0, min(100, score)), 2)

    def _returns(self, values: list[float]) -> list[float]:
        if not values:
            return []
        base = max(1, abs(mean(values)) or 1)
        return [value / base for value in values]

    def _sharpe(self, values: list[float]) -> float:
        if len(values) < 2:
            return 0
        deviation = pstdev(values)
        return round(mean(values) / deviation, 2) if deviation else 0

    def _sortino(self, values: list[float]) -> float:
        downside = [value for value in values if value < 0]
        if len(values) < 2 or not downside:
            return 0
        deviation = pstdev(downside)
        return round(mean(values) / deviation, 2) if deviation else 0

    def _max_drawdown(self, values: list[float]) -> float:
        peak = 0.0
        equity = 0.0
        drawdown = 0.0
        for value in values:
            equity += value
            peak = max(peak, equity)
            drawdown = min(drawdown, equity - peak)
        return round(drawdown, 2)


def _clean(document: dict | None) -> dict:
    if not document:
        return {}
    item = dict(document)
    item.pop("_id", None)
    for key, value in list(item.items()):
        if isinstance(value, datetime):
            item[key] = value.isoformat()
    return item


def _is_number(value: Any) -> bool:
    try:
        number = float(value)
        return math.isfinite(number)
    except (TypeError, ValueError):
        return False


def _risk_reward_number(value: Any) -> float:
    text = str(value or "")
    if ":" in text:
        try:
            return float(text.split(":")[-1])
        except ValueError:
            return 0
    try:
        return float(text)
    except ValueError:
        return 0
