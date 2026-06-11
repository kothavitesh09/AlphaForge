class SentimentService:
    async def market_sentiment(self) -> dict:
        return {"news": 0.0, "social": 0.0, "dominance": 0.0, "summary": "Neutral external sentiment"}

    async def symbol_sentiment(self, symbol: str) -> dict:
        return {"symbol": symbol.upper(), "news": 0.0, "social": 0.0, "score": 0.0}
