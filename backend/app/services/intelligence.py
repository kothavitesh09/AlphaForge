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

            opportunities = sorted(opportunities, key=lambda row: (row["alpha_score"], row["expected_return"], row["confidence"]), reverse=True)
            for index, row in enumerate(opportunities, 1):
                row["rank"] = index
                await self.db.opportunities.update_one({"symbol": row["symbol"]}, {"$set": {"rank": index, "updated_at": now_utc()}})
                await self.db.alpha_scores.update_one({"symbol": row["symbol"]}, {"$set": {"rank": index, "updated_at": now_utc()}})

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
        predictions = [_clean(row) async for row in self.db.predictions.find({"symbol": symbol}).sort([("created_at", -1)]).limit(20)]
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
        prediction_moves = [float(row.get("predicted_change_pct", 0)) for row in context["predictions"] if row.get("predicted_change_pct") is not None]
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
        prediction_quality = mean([float(row.get("confidence", 0)) for row in predictions[:4]]) if predictions else 0
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
        if volatility >= 4 or volume_ratio >= 2.2:
            regime = "HIGH_VOLATILITY"
        elif adx >= 28 and volume_ratio >= 1.5:
            regime = "BREAKOUT"
        elif ema20 > ema50 > ema200 and adx >= 18:
            regime = "BULL"
        elif ema20 < ema50 < ema200 and adx >= 18:
            regime = "BEAR"
        else:
            regime = "RANGE"
        confidence = round(max(1, min(99, adx * 1.6 + min(30, volume_ratio * 10) + min(25, volatility * 4))), 2)
        return {
            "symbol": context["symbol"],
            "regime": regime,
            "confidence": confidence,
            "inputs": {"ema20": ema20, "ema50": ema50, "ema200": ema200, "adx": adx, "atr": atr, "volatility": round(volatility, 4), "volume_ratio": volume_ratio},
            "created_at": now_utc(),
        }

    def _opportunity(self, context: dict, forecast: dict, alpha: dict, regime: dict) -> dict:
        expected_return = float(forecast.get("expected_return", 0))
        risk_score = round(max(1, min(100, 100 - alpha["components"]["risk_reward"] + abs(expected_return) * 1.5)), 2)
        return {
            "symbol": context["symbol"],
            "alpha_score": alpha["alpha_score"],
            "expected_return": round(expected_return, 4),
            "confidence": alpha["confidence"],
            "risk_score": risk_score,
            "rank": 0,
            "market_regime": regime["regime"],
            "forecast_24h": forecast["forecast_24h"],
            "forecast_48h": forecast["forecast_48h"],
            "forecast_7d": forecast["forecast_7d"],
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
