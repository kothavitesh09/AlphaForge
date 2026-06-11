import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import mean, pstdev
from app.core.config import SUPPORTED_SYMBOLS
from app.repositories.base import MongoRepository, now_utc
from app.services.advanced_indicators import AdvancedIndicatorEngine
from app.services.market_trend import MarketTrendEngine


class AnalyticsEngine:
    def __init__(self, db):
        self.db = db

    async def overview(self) -> dict:
        stats = await self.update()
        return {
            "metrics": stats["metrics"],
            "charts": {
                "accuracy_trend": await self.accuracy_trend(),
                "signal_performance": await self.signal_performance(),
                "profit_curve": await self.profit_curve(),
                "prediction_distribution": await self.prediction_distribution(),
            },
            "tables": {
                "best_symbols": await self.symbol_table(best=True),
                "worst_symbols": await self.symbol_table(best=False),
                "recent_predictions": await MongoRepository(self.db, "predictions").find_many(limit=25, sort=[("created_at", -1)]),
                "recent_results": await MongoRepository(self.db, "prediction_results").find_many(limit=25, sort=[("resolved_at", -1)]),
            },
            "backtests": await MongoRepository(self.db, "backtest_results").find_many(limit=50, sort=[("created_at", -1)]),
        }

    async def update(self) -> dict:
        results = await MongoRepository(self.db, "prediction_results").find_many(limit=100000, sort=[("resolved_at", -1)])
        predictions_count = await self.db.predictions.count_documents({})
        signals_count = await self.db.signals.count_documents({})
        validations = await MongoRepository(self.db, "signal_validations").find_many(limit=100000, sort=[("created_at", -1)])
        trades = await MongoRepository(self.db, "paper_trades").find_many(limit=100000, sort=[("created_at", -1)])
        backtests = await MongoRepository(self.db, "backtest_results").find_many(limit=10000, sort=[("created_at", -1)])

        correct = len([row for row in results if row.get("correct")])
        returns = [float(row.get("return_percent", 0)) for row in results]
        validation_returns = [float(row.get("return_percent", 0)) for row in validations if row.get("outcome") in {"WIN", "LOSS", "BREAKEVEN"}]
        trade_pnl = [float(row.get("pnl", 0)) for row in trades if row.get("side") in {"CLOSE", "SELL"}]
        combined_returns = validation_returns or returns
        wins = [value for value in combined_returns if value > 0]
        losses = [abs(value) for value in combined_returns if value < 0]
        confidences = [float(row.get("confidence", 0)) for row in results]
        backtest_returns = [float(row.get("average_return", 0)) for row in backtests]

        metrics = {
            "prediction_accuracy": round(correct / len(results) * 100, 2) if results else 0,
            "win_rate": round(len(wins) / len(combined_returns) * 100, 2) if combined_returns else 0,
            "profit_factor": round(sum(wins) / sum(losses), 2) if losses else round(sum(wins), 2) if wins else 0,
            "average_return": round(mean(combined_returns), 4) if combined_returns else 0,
            "average_confidence": round(mean(confidences), 2) if confidences else 0,
            "sharpe_ratio": self.sharpe(combined_returns or backtest_returns),
            "max_drawdown": self.max_drawdown(combined_returns or backtest_returns),
            "total_predictions": predictions_count,
            "total_signals": signals_count,
            "correct_predictions": correct,
            "incorrect_predictions": len(results) - correct,
        }
        record = {"scope": "global", "metrics": metrics, "created_at": now_utc(), "updated_at": now_utc()}
        await self.db.analytics_stats.update_one({"scope": "global"}, {"$set": record, "$setOnInsert": {"first_created_at": now_utc()}}, upsert=True)
        return record

    async def accuracy_trend(self) -> list[dict]:
        rows = await MongoRepository(self.db, "prediction_results").find_many(limit=5000, sort=[("resolved_at", 1)])
        buckets = defaultdict(lambda: {"total": 0, "correct": 0})
        for row in rows:
            key = str(row.get("resolved_timestamp") or row.get("resolved_at") or "")[:10]
            if not key:
                continue
            buckets[key]["total"] += 1
            buckets[key]["correct"] += 1 if row.get("correct") else 0
        return [{"date": key, "accuracy": round(value["correct"] / value["total"] * 100, 2), **value} for key, value in sorted(buckets.items())]

    async def signal_performance(self) -> list[dict]:
        rows = await MongoRepository(self.db, "signal_validations").find_many(limit=100000, sort=[("created_at", -1)])
        grouped = defaultdict(lambda: {"total": 0, "wins": 0, "losses": 0, "breakeven": 0, "return": 0.0})
        for row in rows:
            key = row.get("action") or row.get("signal") or "UNKNOWN"
            grouped[key]["total"] += 1
            grouped[key]["wins"] += 1 if row.get("outcome") == "WIN" else 0
            grouped[key]["losses"] += 1 if row.get("outcome") == "LOSS" else 0
            grouped[key]["breakeven"] += 1 if row.get("outcome") == "BREAKEVEN" else 0
            grouped[key]["return"] += float(row.get("return_percent", 0))
        return [{"signal": key, **value, "average_return": round(value["return"] / value["total"], 4) if value["total"] else 0} for key, value in grouped.items()]

    async def profit_curve(self) -> list[dict]:
        rows = await MongoRepository(self.db, "signal_validations").find_many(limit=5000, sort=[("created_at", 1)])
        equity = 0.0
        curve = []
        for row in rows:
            equity += float(row.get("return_percent", 0))
            curve.append({"timestamp": str(row.get("created_at")), "equity": round(equity, 4), "symbol": row.get("symbol")})
        return curve

    async def prediction_distribution(self) -> list[dict]:
        rows = await MongoRepository(self.db, "predictions").find_many(limit=100000, sort=[("created_at", -1)])
        counts = Counter(str(row.get("direction", "UNKNOWN")).upper() for row in rows)
        return [{"direction": key, "count": value} for key, value in counts.items()]

    async def symbol_table(self, best: bool) -> list[dict]:
        rows = await MongoRepository(self.db, "prediction_results").find_many(limit=100000, sort=[("resolved_at", -1)])
        grouped = defaultdict(lambda: {"total": 0, "correct": 0, "return": 0.0})
        for row in rows:
            symbol = row.get("symbol")
            if not symbol:
                continue
            grouped[symbol]["total"] += 1
            grouped[symbol]["correct"] += 1 if row.get("correct") else 0
            grouped[symbol]["return"] += float(row.get("return_percent", 0))
        table = [
            {
                "symbol": symbol,
                "total": value["total"],
                "accuracy": round(value["correct"] / value["total"] * 100, 2) if value["total"] else 0,
                "average_return": round(value["return"] / value["total"], 4) if value["total"] else 0,
            }
            for symbol, value in grouped.items()
        ]
        return sorted(table, key=lambda row: (row["accuracy"], row["average_return"]), reverse=best)[:10]

    def sharpe(self, values: list[float]) -> float:
        if len(values) < 2:
            return 0
        deviation = pstdev(values)
        return round(mean(values) / deviation, 2) if deviation else 0

    def max_drawdown(self, values: list[float]) -> float:
        peak = 0.0
        equity = 0.0
        drawdown = 0.0
        for value in values:
            equity += value
            peak = max(peak, equity)
            drawdown = min(drawdown, equity - peak)
        return round(drawdown, 4)


class MarketSentimentEngine:
    def __init__(self, db):
        self.db = db

    async def update(self) -> dict:
        latest_indicators = []
        for symbol in SUPPORTED_SYMBOLS:
            doc = await self.db.indicator_data.find_one({"symbol": symbol}, sort=[("timestamp", -1)])
            if doc:
                latest_indicators.append(doc)
        signals = await MongoRepository(self.db, "signals").find_many(limit=200, sort=[("created_at", -1)])
        score = 50.0
        if latest_indicators:
            rsi = mean(float(row.get("rsi", 50)) for row in latest_indicators)
            macd_bullish = len([row for row in latest_indicators if float(row.get("macd", 0)) >= float(row.get("macd_signal", 0))])
            volume = mean(float(row.get("volume_ratio", 1)) for row in latest_indicators)
            score += max(-15, min(15, (rsi - 50) * 0.5))
            score += (macd_bullish / len(latest_indicators) - 0.5) * 20
            score += max(-10, min(10, (volume - 1) * 8))
        if signals:
            buys = len([row for row in signals if row.get("signal") == "BUY"])
            sells = len([row for row in signals if row.get("signal") == "SELL"])
            score += max(-15, min(15, (buys - sells) / len(signals) * 30))
        score = round(max(0, min(100, score)), 2)
        label = "Bullish" if score >= 60 else "Bearish" if score <= 40 else "Neutral"
        record = {"label": label, "score": score, "inputs": {"indicators": len(latest_indicators), "signals": len(signals)}, "created_at": now_utc()}
        await self.db.market_sentiment.insert_one(record)
        return {**record, "created_at": record["created_at"].isoformat()}

    async def latest(self) -> dict:
        doc = await self.db.market_sentiment.find_one(sort=[("created_at", -1)])
        if doc:
            doc.pop("_id", None)
            if isinstance(doc.get("created_at"), datetime):
                doc["created_at"] = doc["created_at"].isoformat()
            return doc
        return await self.update()


class SignalValidationService:
    def __init__(self, db):
        self.db = db

    async def validate_all(self) -> dict:
        signals = await MongoRepository(self.db, "signals").find_many(limit=100000, sort=[("created_at", -1)])
        created = 0
        updated = 0
        for signal in signals:
            result = await self.validate(signal)
            if result.get("created"):
                created += 1
            elif result.get("stored"):
                updated += 1
        return {"created": created, "updated": updated}

    async def validate(self, signal: dict) -> dict:
        signal_id = signal.get("id")
        symbol = signal.get("symbol")
        action = signal.get("action") or signal.get("signal")
        entry = float(signal.get("entry") or signal.get("decision", {}).get("entry_price") or 0)
        target = float(signal.get("target") or signal.get("decision", {}).get("take_profit_1") or 0)
        stop = float(signal.get("stop_loss") or signal.get("decision", {}).get("stop_loss") or 0)
        if not signal_id or not symbol:
            return {"stored": False}
        if action not in {"BUY", "SELL"} or entry <= 0 or target <= 0 or stop <= 0:
            record = {
                "signal_id": signal_id,
                "symbol": symbol,
                "action": action or "NO_TRADE",
                "entry": entry,
                "target": target,
                "stop_loss": stop,
                "outcome": "NON_EXECUTABLE",
                "exit_price": 0,
                "return_percent": 0,
                "signal_quality_score": round(float(signal.get("confidence", 0)) * 0.4 + float(signal.get("score", 0)) * 0.2, 2),
                "created_at": now_utc(),
                "updated_at": now_utc(),
            }
            exists = await self.db.signal_validations.find_one({"signal_id": signal_id})
            await self.db.signal_validations.update_one({"signal_id": signal_id}, {"$set": record}, upsert=True)
            return {"stored": True, "created": exists is None, **record}
        candles = [row async for row in self.db.market_data.find({"symbol": symbol, "interval": "1h"}).sort([("timestamp", 1)]).limit(10000)]
        outcome = "OPEN"
        exit_price = entry
        for candle in candles:
            high = float(candle.get("high", 0))
            low = float(candle.get("low", 0))
            if action == "BUY" and high >= target:
                outcome, exit_price = "WIN", target
                break
            if action == "BUY" and low <= stop:
                outcome, exit_price = "LOSS", stop
                break
            if action == "SELL" and low <= target:
                outcome, exit_price = "WIN", target
                break
            if action == "SELL" and high >= stop:
                outcome, exit_price = "LOSS", stop
                break
        return_percent = 0 if outcome == "OPEN" else ((exit_price / entry - 1) * 100 if action == "BUY" else (entry / exit_price - 1) * 100)
        quality = self.quality_score(signal, outcome, return_percent)
        record = {
            "signal_id": signal_id,
            "symbol": symbol,
            "action": action,
            "entry": entry,
            "target": target,
            "stop_loss": stop,
            "outcome": outcome,
            "exit_price": exit_price,
            "return_percent": round(return_percent, 4),
            "signal_quality_score": quality,
            "created_at": now_utc(),
            "updated_at": now_utc(),
        }
        exists = await self.db.signal_validations.find_one({"signal_id": signal_id})
        await self.db.signal_validations.update_one({"signal_id": signal_id}, {"$set": record}, upsert=True)
        return {"stored": True, "created": exists is None, **record}

    def quality_score(self, signal: dict, outcome: str, return_percent: float) -> float:
        score = float(signal.get("confidence", 0)) * 0.6 + float(signal.get("score", 0)) * 0.25
        score += 15 if outcome == "WIN" else -15 if outcome == "LOSS" else 0
        score += max(-10, min(10, return_percent * 2))
        return round(max(0, min(100, score)), 2)
