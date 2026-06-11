from datetime import timedelta
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
        total = len(rows)
        correct = len([row for row in rows if row.get("correct")])
        confidence = [float(row.get("confidence", 0)) for row in rows]
        return {
            "timeframe": timeframe,
            "total_predictions": total,
            "correct_predictions": correct,
            "incorrect_predictions": total - correct,
            "accuracy_percent": round(correct / total * 100, 2) if total else 0,
            "average_confidence": round(sum(confidence) / len(confidence), 2) if confidence else 0,
        }
