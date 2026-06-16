from datetime import timedelta
from collections import defaultdict
from app.repositories.base import MongoRepository, now_utc


class AccuracyService:
    def __init__(self, db):
        self.results = MongoRepository(db, "prediction_results")
        self.stats = MongoRepository(db, "accuracy_stats")

    async def summary(self, timeframe: str = "all") -> dict:
        since = None
        if timeframe == "daily":
            since = now_utc() - timedelta(days=1)
        elif timeframe == "weekly":
            since = now_utc() - timedelta(days=7)
        elif timeframe == "monthly":
            since = now_utc() - timedelta(days=30)
        query = {"resolved_at": {"$gte": since}} if since else {}
        rows = await self.results.find_many(query, limit=5000, sort=[("resolved_at", -1)])
        live_rows = [row for row in rows if row.get("source_type") == "live"]
        scoped_rows = live_rows or rows
        total = len(scoped_rows)
        correct = len([row for row in scoped_rows if row.get("correct")])
        confidence = [float(row.get("confidence", 0)) for row in scoped_rows]
        absolute_errors = [float(row.get("absolute_error", 0)) for row in scoped_rows if row.get("absolute_error") is not None]
        percentage_errors = [float(row.get("absolute_percentage_error", 0)) for row in scoped_rows if row.get("absolute_percentage_error") is not None]
        squared_errors = [value * value for value in absolute_errors]
        return {
            "timeframe": timeframe,
            "source_type": "live" if live_rows else "all",
            "total_predictions": total,
            "correct_predictions": correct,
            "incorrect_predictions": total - correct,
            "accuracy_percent": round(correct / total * 100, 2) if total else 0,
            "average_confidence": round(sum(confidence) / len(confidence), 2) if confidence else 0,
            "mae": round(sum(absolute_errors) / len(absolute_errors), 6) if absolute_errors else 0,
            "mape": round(sum(percentage_errors) / len(percentage_errors), 6) if percentage_errors else 0,
            "rmse": round((sum(squared_errors) / len(squared_errors)) ** 0.5, 6) if squared_errors else 0,
            "by_asset": self._breakdown(scoped_rows, "symbol"),
            "by_timeframe": self._breakdown(scoped_rows, "timeframe"),
            "over_time": self._over_time(scoped_rows),
        }

    def _breakdown(self, rows: list[dict], field: str) -> list[dict]:
        buckets = defaultdict(lambda: {"total": 0, "correct": 0})
        for row in rows:
            key = row.get(field) or "UNKNOWN"
            buckets[key]["total"] += 1
            buckets[key]["correct"] += 1 if row.get("correct") else 0
        return [
            {
                field: key,
                "total": value["total"],
                "correct": value["correct"],
                "accuracy": round(value["correct"] / value["total"] * 100, 2) if value["total"] else 0,
            }
            for key, value in sorted(buckets.items())
        ]

    def _over_time(self, rows: list[dict]) -> list[dict]:
        buckets = defaultdict(lambda: {"total": 0, "correct": 0})
        for row in rows:
            key = str(row.get("resolved_timestamp") or row.get("resolved_at") or "")[:10]
            if not key:
                continue
            buckets[key]["total"] += 1
            buckets[key]["correct"] += 1 if row.get("correct") else 0
        return [
            {
                "date": key,
                "total": value["total"],
                "correct": value["correct"],
                "accuracy": round(value["correct"] / value["total"] * 100, 2) if value["total"] else 0,
            }
            for key, value in sorted(buckets.items())
        ]
