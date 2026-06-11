from app.repositories.base import MongoRepository
from app.services.market_data import MarketDataClient
from app.services.market_trend import MarketTrendEngine


class DashboardService:
    def __init__(self, db):
        self.db = db
        self.market = MarketDataClient()
        self.signals = MongoRepository(db, "signals")
        self.results = MongoRepository(db, "prediction_results")
        self.predictions = MongoRepository(db, "predictions")
        self.trades = MongoRepository(db, "paper_trades")
        self.portfolios = MongoRepository(db, "portfolios")

    async def overview(self) -> dict:
        tickers = sorted(await self.market.tickers(), key=lambda item: item.get("volume_24h", 0), reverse=True)[:20]
        latest_signals = await self.signals.find_many(limit=50, sort=[("created_at", -1)])
        buy = [item for item in latest_signals if item["signal"] == "BUY"][:5]
        sell = [item for item in latest_signals if item["signal"] == "SELL"][:5]
        results = await self.results.find_many(limit=1000, sort=[("resolved_at", -1)])
        correct = len([item for item in results if item.get("correct")])
        accuracy = round(correct / len(results) * 100, 2) if results else 0
        market_score = sum(float(t.get("change_24h", 0)) for t in tickers[:10])
        trend = "Bullish" if market_score > 0 else "Bearish" if market_score < 0 else "Neutral"
        gainers = sorted(tickers, key=lambda item: item.get("change_24h", 0), reverse=True)[:5]
        losers = sorted(tickers, key=lambda item: item.get("change_24h", 0))[:5]
        recent_predictions = await self.predictions.find_many(limit=8, sort=[("created_at", -1)])
        recent_trades = await self.trades.find_many(limit=8, sort=[("created_at", -1)])
        portfolio_docs = await self.portfolios.find_many(limit=100)
        portfolio_value = round(sum(float(p.get("cash_balance", 0)) for p in portfolio_docs), 2)
        active_signals = len([item for item in latest_signals if item["signal"] in {"BUY", "SELL"}])
        return {
            "market_sentiment": {"label": trend, "score": round(max(0, min(100, 50 + market_score)), 2)},
            "market_overview": tickers,
            "market_trend": trend,
            "active_signals": active_signals,
            "portfolio_value": portfolio_value,
            "top_buy_signals": buy,
            "top_sell_signals": sell,
            "top_gainers": gainers,
            "top_losers": losers,
            "recent_predictions": recent_predictions,
            "recent_trades": recent_trades,
            "prediction_accuracy": {"predictions": len(results), "correct": correct, "accuracy": accuracy},
        }

    async def coin_rows(self) -> list[dict]:
        tickers = await self.market.tickers()
        signals = await self.signals.find_many(limit=500, sort=[("created_at", -1)])
        latest_by_symbol = {}
        for signal in signals:
            latest_by_symbol.setdefault(signal["symbol"], signal)
        rows = []
        for index, ticker in enumerate(tickers[:60]):
            symbol = ticker["symbol"]
            if index < 12:
                try:
                    trend = MarketTrendEngine().analyze(await self.market.candles(symbol))
                    indicators = trend["indicators"]
                except Exception:
                    trend = {"trend": self.ticker_trend(ticker), "trend_score": 50}
                    indicators = {"rsi": 50}
            else:
                trend = {"trend": self.ticker_trend(ticker), "trend_score": 50 + float(ticker.get("change_24h", 0))}
                indicators = {"rsi": None}
            signal = latest_by_symbol.get(symbol, {})
            rows.append({
                **ticker,
                "trend": trend["trend"],
                "trend_score": trend["trend_score"],
                "rsi": indicators.get("rsi", 50),
                "signal": signal.get("signal", "HOLD"),
                "confidence": signal.get("confidence", 0),
            })
        return rows

    def ticker_trend(self, ticker: dict) -> str:
        change = float(ticker.get("change_24h", 0))
        if change > 0:
            return "Bullish"
        if change < 0:
            return "Bearish"
        return "Neutral"
