from app.core.config import SUPPORTED_SYMBOLS
from app.repositories.base import now_utc


FEATURES = ("rsi", "macd", "ema20", "ema50", "ema200", "atr", "adx", "volume_ratio", "trend_score")
MODELS = ("random_forest", "xgboost", "lightgbm")


class MLDatasetService:
    def __init__(self, db):
        self.db = db

    async def build(self, symbols: list[str] | None = None, timeframe: str = "1h", limit_per_symbol: int = 5000) -> dict:
        symbols = [symbol.upper() for symbol in (symbols or list(SUPPORTED_SYMBOLS)) if symbol.upper() in SUPPORTED_SYMBOLS]
        rows = []
        skipped = []
        for symbol in symbols:
            indicators = [
                row
                async for row in self.db.indicator_data.find({"symbol": symbol, "interval": timeframe}).sort([("timestamp", 1)]).limit(limit_per_symbol)
            ]
            if not indicators:
                skipped.append({"symbol": symbol, "reason": "no_indicator_rows"})
                continue
            for item in indicators:
                label = await self._label(symbol, timeframe, item.get("timestamp"))
                if not label:
                    continue
                rows.append({
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "timestamp": item.get("timestamp"),
                    "features": {name: float(item.get(name, item.get("volume_ratio", 0)) or 0) for name in FEATURES},
                    "label": label,
                })
        dataset = {
            "models": list(MODELS),
            "timeframe": timeframe,
            "feature_columns": list(FEATURES),
            "label_values": ["UP", "DOWN", "SIDEWAYS"],
            "row_count": len(rows),
            "rows": rows,
            "skipped": skipped,
            "created_at": now_utc(),
        }
        await self.db.ml_datasets.insert_one(dataset)
        dataset.pop("_id", None)
        dataset["created_at"] = dataset["created_at"].isoformat()
        return dataset

    async def latest(self) -> dict | None:
        doc = await self.db.ml_datasets.find_one(sort=[("created_at", -1)])
        if not doc:
            return None
        doc["id"] = str(doc.pop("_id"))
        if hasattr(doc.get("created_at"), "isoformat"):
            doc["created_at"] = doc["created_at"].isoformat()
        doc["rows"] = doc.get("rows", [])[:100]
        return doc

    async def _label(self, symbol: str, timeframe: str, timestamp: str | None) -> str | None:
        if not timestamp:
            return None
        current = await self.db.market_data.find_one({"symbol": symbol, "interval": timeframe, "timestamp": timestamp})
        future = await self.db.market_data.find_one({"symbol": symbol, "interval": timeframe, "timestamp": {"$gt": timestamp}}, sort=[("timestamp", 1)])
        if not current or not future:
            return None
        start = float(current.get("close") or 0)
        end = float(future.get("close") or 0)
        if start <= 0:
            return None
        change = end / start - 1
        if change > 0.003:
            return "UP"
        if change < -0.003:
            return "DOWN"
        return "SIDEWAYS"
