import importlib.util
import math
import pickle
from collections import Counter, defaultdict
from datetime import datetime
from statistics import mean, pstdev
from typing import Any
from bson.binary import Binary
import numpy as np
import pandas as pd
from pymongo import UpdateOne
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_score, recall_score
from sklearn.preprocessing import LabelEncoder
from xgboost import XGBClassifier
from app.core.config import SUPPORTED_SYMBOLS
from app.repositories.base import MongoRepository, now_utc
from app.services.advanced_indicators import AdvancedIndicatorEngine
from app.services.indicators import calculate_indicators
from app.services.market_trend import MarketTrendEngine


ML_SYMBOLS = ("BTC_INR", "ETH_INR", "SOL_INR", "BNB_INR", "XRP_INR", "DOGE_INR", "TRX_INR", "DOT_INR", "AVAX_INR", "ATOM_INR", "BDX_INR")
ML_TIMEFRAMES = ("15m", "1h", "4h", "1d")
LABELS = ("DOWN", "SIDEWAYS", "UP")
FEATURE_COLUMNS = (
    "rsi",
    "macd",
    "macd_signal",
    "macd_histogram",
    "ema20",
    "ema50",
    "ema200",
    "atr",
    "adx",
    "vwap",
    "obv",
    "volume",
    "volume_spike",
    "trend_score",
    "market_sentiment_score",
    "support_distance",
    "resistance_distance",
    "price_momentum",
    "volatility",
)


class MLTrainingService:
    def __init__(self, db):
        self.db = db

    async def run(self, symbols: list[str] | None = None, timeframes: list[str] | None = None, limit_per_symbol: int = 10000) -> dict:
        symbols = [item.upper() for item in (symbols or list(ML_SYMBOLS)) if item.upper() in SUPPORTED_SYMBOLS]
        timeframes = [item for item in (timeframes or list(ML_TIMEFRAMES)) if item in ML_TIMEFRAMES]
        features = await self.build_feature_store(symbols, timeframes, limit_per_symbol)
        labels = await self.build_labels(symbols, timeframes)
        training = await self.train_models(symbols, timeframes)
        predictions = await self.create_ml_predictions(symbols, timeframes)
        ensemble = await self.create_ensemble_predictions(symbols, timeframes)
        return {"features": features, "labels": labels, "training": training, "predictions": predictions, "ensemble": ensemble}

    async def build_feature_store(self, symbols: list[str], timeframes: list[str], limit_per_symbol: int = 10000) -> dict:
        sentiment = await self.db.market_sentiment.find_one(sort=[("created_at", -1)])
        sentiment_score = float((sentiment or {}).get("score", 50))
        inserted = 0
        updated = 0
        skipped = []
        for symbol in symbols:
            for timeframe in timeframes:
                candles = [
                    _clean(row)
                    async for row in self.db.market_data.find({"symbol": symbol, "interval": timeframe}).sort([("timestamp", 1)]).limit(limit_per_symbol)
                ]
                if len(candles) < 30:
                    skipped.append({"symbol": symbol, "timeframe": timeframe, "reason": "insufficient_candles", "candles": len(candles)})
                    continue
                rows = self._feature_rows(symbol, timeframe, candles, sentiment_score)
                result = await self._bulk_upsert("ml_features", rows, ("symbol", "timeframe", "timestamp"))
                inserted += result["inserted"]
                updated += result["updated"]
        return {"inserted": inserted, "updated": updated, "skipped": skipped}

    async def build_labels(self, symbols: list[str], timeframes: list[str]) -> dict:
        inserted = 0
        updated = 0
        skipped = []
        for symbol in symbols:
            for timeframe in timeframes:
                features = [_clean(row) async for row in self.db.ml_features.find({"symbol": symbol, "timeframe": timeframe}).sort([("timestamp", 1)])]
                if len(features) < 2:
                    skipped.append({"symbol": symbol, "timeframe": timeframe, "reason": "insufficient_features", "features": len(features)})
                    continue
                labels = []
                for index, row in enumerate(features[:-1]):
                    future = features[index + 1]
                    current_close = float(row.get("close", 0))
                    future_close = float(future.get("close", 0))
                    if current_close <= 0:
                        continue
                    future_return = future_close / current_close - 1
                    label = "UP" if future_return > 0.003 else "DOWN" if future_return < -0.003 else "SIDEWAYS"
                    labels.append({
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "timestamp": row["timestamp"],
                        "future_timestamp": future["timestamp"],
                        "future_return": round(future_return * 100, 6),
                        "label": label,
                        "created_at": now_utc(),
                    })
                result = await self._bulk_upsert("ml_labels", labels, ("symbol", "timeframe", "timestamp"))
                inserted += result["inserted"]
                updated += result["updated"]
        return {"inserted": inserted, "updated": updated, "skipped": skipped}

    async def train_models(self, symbols: list[str], timeframes: list[str]) -> dict:
        outputs = []
        for timeframe in timeframes:
            dataset = await self._dataset(symbols, timeframe)
            if len(dataset) < 60:
                outputs.append({"timeframe": timeframe, "status": "skipped", "reason": "insufficient_labeled_samples", "samples": len(dataset)})
                continue
            train, validation, test = self._split(dataset)
            for model_name in ("rule_based", "random_forest", "xgboost", "lightgbm"):
                result = await self._train_one(model_name, timeframe, train, validation, test)
                outputs.append(result)
        return {"results": outputs}

    async def create_ml_predictions(self, symbols: list[str], timeframes: list[str]) -> dict:
        latest_versions = await self._latest_model_versions()
        inserted = 0
        skipped = []
        for symbol in symbols:
            for timeframe in timeframes:
                feature = await self.db.ml_features.find_one({"symbol": symbol, "timeframe": timeframe}, sort=[("timestamp", -1)])
                if not feature:
                    skipped.append({"symbol": symbol, "timeframe": timeframe, "reason": "no_features"})
                    continue
                for model in ("random_forest", "xgboost", "lightgbm"):
                    version = latest_versions.get((model, timeframe))
                    if not version:
                        continue
                    prediction, probability = self._predict_with_model(feature, version)
                    doc = {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "timestamp": feature["timestamp"],
                        "model": model,
                        "prediction": prediction,
                        "probability": probability,
                        "model_version": version.get("version"),
                        "created_at": now_utc(),
                    }
                    await self.db.ml_predictions.update_one(
                        {"symbol": symbol, "timeframe": timeframe, "timestamp": feature["timestamp"], "model": model},
                        {"$set": doc},
                        upsert=True,
                    )
                    inserted += 1
        return {"created": inserted, "skipped": skipped}

    async def create_ensemble_predictions(self, symbols: list[str], timeframes: list[str]) -> dict:
        created = 0
        skipped = []
        for symbol in symbols:
            for timeframe in timeframes:
                ml_rows = [row async for row in self.db.ml_predictions.find({"symbol": symbol, "timeframe": timeframe}).sort([("timestamp", -1)]).limit(4)]
                rule = await self.db.predictions.find_one({"symbol": symbol, "timeframe": timeframe}, sort=[("created_at", -1)])
                if not ml_rows and not rule:
                    skipped.append({"symbol": symbol, "timeframe": timeframe, "reason": "no_predictions"})
                    continue
                votes = defaultdict(float)
                components = []
                if rule:
                    direction = str(rule.get("direction", "SIDEWAYS")).upper()
                    confidence = float(rule.get("confidence", 50))
                    votes[direction] += confidence * 0.25
                    components.append({"model": "rule_based", "prediction": direction, "probability": confidence})
                for row in ml_rows:
                    direction = str(row.get("prediction", "SIDEWAYS")).upper()
                    probability = float(row.get("probability", 0))
                    votes[direction] += probability * 0.25
                    components.append({"model": row.get("model"), "prediction": direction, "probability": probability})
                final_direction = max(votes, key=votes.get)
                confidence = round(votes[final_direction] / max(1, len(components) * 0.25), 2)
                action = "BUY" if final_direction == "UP" else "SELL" if final_direction == "DOWN" else "HOLD"
                timestamp = (ml_rows[0]["timestamp"] if ml_rows else rule.get("source_timestamp"))
                doc = {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "timestamp": timestamp,
                    "final_prediction": final_direction,
                    "action": action,
                    "confidence": confidence,
                    "components": components,
                    "created_at": now_utc(),
                }
                await self.db.ensemble_predictions.update_one(
                    {"symbol": symbol, "timeframe": timeframe, "timestamp": timestamp},
                    {"$set": doc},
                    upsert=True,
                )
                created += 1
        return {"created": created, "skipped": skipped}

    async def dashboard(self) -> dict:
        results = await MongoRepository(self.db, "ml_model_results").find_many(limit=100, sort=[("created_at", -1)])
        predictions = await MongoRepository(self.db, "ml_predictions").find_many(limit=200, sort=[("created_at", -1)])
        ensemble = await MongoRepository(self.db, "ensemble_predictions").find_many(limit=100, sort=[("created_at", -1)])
        latest_by_model = {}
        for result in results:
            latest_by_model.setdefault((result.get("model"), result.get("timeframe")), result)
        trained = [item for item in latest_by_model.values() if item.get("status") == "trained"]
        best = max(trained, key=lambda item: item.get("metrics", {}).get("f1", 0), default=None)
        top_features = self._top_features(trained)
        return {
            "models": list(latest_by_model.values()),
            "best_model": best,
            "top_features": top_features,
            "prediction_distribution": [{"prediction": key, "count": value} for key, value in Counter(row.get("prediction") for row in predictions).items()],
            "ensemble_predictions": ensemble,
            "recent_ml_predictions": predictions[:50],
        }

    def _feature_rows(self, symbol: str, timeframe: str, candles: list[dict], sentiment_score: float) -> list[dict]:
        df = calculate_indicators(candles)
        df["timestamp"] = [item["timestamp"] for item in candles]
        df["sma20"] = df["close"].rolling(20).mean().fillna(df["close"])
        df["obv"] = (np.sign(df["close"].diff()).fillna(0) * df["volume"]).cumsum()
        typical = (df["high"] + df["low"] + df["close"]) / 3
        df["vwap"] = (typical * df["volume"]).cumsum() / df["volume"].cumsum().replace(0, np.nan)
        df["adx"] = AdvancedIndicatorEngine().adx(df)
        df["price_momentum"] = df["close"].pct_change(5).fillna(0) * 100
        df["macd_histogram"] = df["macd"] - df["macd_signal"]
        rows = []
        for index, row in df.iterrows():
            if index < 30:
                continue
            window = df.iloc[max(0, index - 80) : index + 1]
            support = float(window["low"].min())
            resistance = float(window["high"].max())
            close = float(row["close"])
            trend = MarketTrendEngine().analyze(candles[max(0, index - 240) : index + 1])
            rows.append({
                "symbol": symbol,
                "timeframe": timeframe,
                "timestamp": str(row["timestamp"]),
                "close": close,
                "features": {
                    "rsi": _finite(row["rsi"]),
                    "macd": _finite(row["macd"]),
                    "macd_signal": _finite(row["macd_signal"]),
                    "macd_histogram": _finite(row["macd_histogram"]),
                    "ema20": _finite(row["ema20"]),
                    "ema50": _finite(row["ema50"]),
                    "ema200": _finite(row["ema200"]),
                    "atr": _finite(row["atr"]),
                    "adx": _finite(row["adx"]),
                    "vwap": _finite(row["vwap"]),
                    "obv": _finite(row["obv"]),
                    "volume": _finite(row["volume"]),
                    "volume_spike": 1.0 if _finite(row["volume_ratio"]) >= 1.8 else 0.0,
                    "trend_score": float(trend.get("trend_score", 50)),
                    "market_sentiment_score": sentiment_score,
                    "support_distance": ((close - support) / close * 100) if close else 0,
                    "resistance_distance": ((resistance - close) / close * 100) if close else 0,
                    "price_momentum": _finite(row["price_momentum"]),
                    "volatility": _finite(row["volatility"]),
                },
                "created_at": now_utc(),
            })
        return rows

    async def _dataset(self, symbols: list[str], timeframe: str) -> list[dict]:
        rows = []
        async for label in self.db.ml_labels.find({"symbol": {"$in": symbols}, "timeframe": timeframe}).sort([("timestamp", 1)]):
            feature = await self.db.ml_features.find_one({"symbol": label["symbol"], "timeframe": timeframe, "timestamp": label["timestamp"]})
            if feature:
                rows.append({"symbol": label["symbol"], "timestamp": label["timestamp"], "features": feature["features"], "label": label["label"], "future_return": label.get("future_return", 0)})
        return rows

    async def _train_one(self, model_name: str, timeframe: str, train: list[dict], validation: list[dict], test: list[dict]) -> dict:
        version = f"{model_name}-{timeframe}-{int(datetime.utcnow().timestamp())}"
        if model_name == "lightgbm" and not importlib.util.find_spec("lightgbm"):
            result = {"model": model_name, "timeframe": timeframe, "status": "unavailable", "reason": "lightgbm package is not installed", "version": version, "created_at": now_utc()}
            await self.db.ml_model_results.insert_one(result)
            return _serializable(result)
        x_train, y_train = self._xy(train)
        x_test, y_test = self._xy(test)
        if len(set(y_train)) < 2 or len(x_test) == 0:
            result = {"model": model_name, "timeframe": timeframe, "status": "skipped", "reason": "insufficient_label_diversity", "samples": len(train) + len(validation) + len(test), "version": version, "created_at": now_utc()}
            await self.db.ml_model_results.insert_one(result)
            return _serializable(result)
        encoder = LabelEncoder().fit(list(LABELS))
        y_train_encoded = encoder.transform(y_train)
        if model_name == "rule_based":
            y_pred = [self._rule_predict(row["features"]) for row in test]
            feature_importance = []
        else:
            model = self._model(model_name)
            model.fit(x_train, y_train_encoded)
            y_pred = encoder.inverse_transform(model.predict(x_test))
            feature_importance = self._importance(model)
            await self.db.ml_model_versions.insert_one({
                "model": model_name,
                "timeframe": timeframe,
                "version": version,
                "feature_columns": list(FEATURE_COLUMNS),
                "classes": list(encoder.classes_),
                "artifact_format": "pickle",
                "artifact": Binary(pickle.dumps(model)),
                "created_at": now_utc(),
            })
        metrics = self._metrics(y_test, list(y_pred), [row.get("future_return", 0) for row in test])
        result = {
            "model": model_name,
            "timeframe": timeframe,
            "status": "trained",
            "version": version,
            "samples": {"train": len(train), "validation": len(validation), "test": len(test), "total": len(train) + len(validation) + len(test)},
            "metrics": metrics,
            "feature_importance": feature_importance,
            "created_at": now_utc(),
        }
        await self.db.ml_model_results.insert_one(result)
        return _serializable(result)

    def _model(self, model_name: str):
        if model_name == "random_forest":
            return RandomForestClassifier(n_estimators=180, max_depth=8, min_samples_leaf=4, random_state=42, class_weight="balanced_subsample")
        if model_name == "xgboost":
            return XGBClassifier(n_estimators=160, max_depth=4, learning_rate=0.06, subsample=0.9, colsample_bytree=0.9, objective="multi:softprob", eval_metric="mlogloss", random_state=42)
        import lightgbm as lgb
        return lgb.LGBMClassifier(n_estimators=180, max_depth=6, learning_rate=0.06, random_state=42)

    def _metrics(self, y_true: list[str], y_pred: list[str], returns: list[float]) -> dict:
        wins = [ret for pred, ret in zip(y_pred, returns) if (pred == "UP" and ret > 0) or (pred == "DOWN" and ret < 0) or (pred == "SIDEWAYS" and abs(ret) <= 0.3)]
        losses = [abs(ret) for pred, ret in zip(y_pred, returns) if not ((pred == "UP" and ret > 0) or (pred == "DOWN" and ret < 0) or (pred == "SIDEWAYS" and abs(ret) <= 0.3))]
        return {
            "accuracy": round(accuracy_score(y_true, y_pred) * 100, 2),
            "precision": round(precision_score(y_true, y_pred, labels=list(LABELS), average="macro", zero_division=0) * 100, 2),
            "recall": round(recall_score(y_true, y_pred, labels=list(LABELS), average="macro", zero_division=0) * 100, 2),
            "f1": round(f1_score(y_true, y_pred, labels=list(LABELS), average="macro", zero_division=0) * 100, 2),
            "win_rate": round(len(wins) / len(y_pred) * 100, 2) if y_pred else 0,
            "profit_factor": round(sum(abs(x) for x in wins) / sum(losses), 2) if losses else round(sum(abs(x) for x in wins), 2) if wins else 0,
            "sharpe_ratio": self._sharpe(returns),
            "confusion_matrix": confusion_matrix(y_true, y_pred, labels=list(LABELS)).tolist(),
        }

    def _predict_with_model(self, feature: dict, version: dict) -> tuple[str, float]:
        model = pickle.loads(bytes(version["artifact"]))
        columns = version.get("feature_columns") or list(FEATURE_COLUMNS)
        classes = version.get("classes") or list(LABELS)
        x_row = [[float(feature.get("features", {}).get(col, 0)) for col in columns]]
        raw_prediction = model.predict(x_row)[0]
        if isinstance(raw_prediction, (np.integer, int)):
            prediction = str(classes[int(raw_prediction)])
        else:
            prediction = str(raw_prediction)
        if hasattr(model, "predict_proba"):
            probability = float(np.max(model.predict_proba(x_row)[0])) * 100
        else:
            probability = 50.0
        return prediction.upper(), round(max(1, min(99, probability)), 2)

    def _rule_predict(self, features: dict) -> str:
        score = 0
        score += 1 if float(features.get("rsi", 50)) > 55 else -1 if float(features.get("rsi", 50)) < 45 else 0
        score += 1 if float(features.get("macd_histogram", 0)) > 0 else -1
        score += 1 if float(features.get("ema20", 0)) > float(features.get("ema50", 0)) else -1
        score += 1 if float(features.get("price_momentum", 0)) > 0 else -1
        if score >= 2:
            return "UP"
        if score <= -2:
            return "DOWN"
        return "SIDEWAYS"

    def _split(self, rows: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
        first = int(len(rows) * 0.7)
        second = int(len(rows) * 0.85)
        return rows[:first], rows[first:second], rows[second:]

    def _xy(self, rows: list[dict]) -> tuple[list[list[float]], list[str]]:
        return [[float(row["features"].get(col, 0)) for col in FEATURE_COLUMNS] for row in rows], [row["label"] for row in rows]

    def _importance(self, model) -> list[dict]:
        values = getattr(model, "feature_importances_", None)
        if values is None:
            return []
        rows = [{"feature": col, "importance": round(float(value), 6)} for col, value in zip(FEATURE_COLUMNS, values)]
        return sorted(rows, key=lambda item: item["importance"], reverse=True)[:20]

    def _top_features(self, results: list[dict]) -> list[dict]:
        totals = defaultdict(float)
        for result in results:
            for item in result.get("feature_importance", []):
                totals[item["feature"]] += float(item["importance"])
        return [{"feature": key, "importance": round(value, 6)} for key, value in sorted(totals.items(), key=lambda item: item[1], reverse=True)[:20]]

    async def _latest_model_results(self) -> dict:
        rows = await MongoRepository(self.db, "ml_model_results").find_many(limit=1000, sort=[("created_at", -1)])
        latest = {}
        for row in rows:
            latest.setdefault((row.get("model"), row.get("timeframe")), row)
        return latest

    async def _latest_model_versions(self) -> dict:
        rows = await MongoRepository(self.db, "ml_model_versions").find_many(limit=1000, sort=[("created_at", -1)])
        latest = {}
        for row in rows:
            latest.setdefault((row.get("model"), row.get("timeframe")), row)
        return latest

    async def _bulk_upsert(self, collection: str, rows: list[dict], keys: tuple[str, ...]) -> dict:
        if not rows:
            return {"inserted": 0, "updated": 0}
        operations = []
        for row in rows:
            query = {key: row[key] for key in keys}
            update_row = dict(row)
            update_row.pop("created_at", None)
            operations.append(UpdateOne(query, {"$set": update_row, "$setOnInsert": {"created_at": row.get("created_at", now_utc())}}, upsert=True))
        result = await self.db[collection].bulk_write(operations, ordered=False)
        return {"inserted": result.upserted_count, "updated": result.modified_count}

    def _sharpe(self, values: list[float]) -> float:
        if len(values) < 2:
            return 0
        deviation = pstdev(values)
        return round(mean(values) / deviation, 2) if deviation else 0


def _finite(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def _clean(document: dict) -> dict:
    item = dict(document)
    item.pop("_id", None)
    return item


def _serializable(document: dict) -> dict:
    item = dict(document)
    item.pop("_id", None)
    for key, value in list(item.items()):
        if isinstance(value, datetime):
            item[key] = value.isoformat()
    return item
