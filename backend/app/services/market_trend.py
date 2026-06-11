from app.services.advanced_indicators import AdvancedIndicatorEngine


class MarketTrendEngine:
    def analyze(self, candles: list[dict]) -> dict:
        indicators = AdvancedIndicatorEngine().calculate(candles)
        if not indicators:
            return {"trend": "Neutral", "trend_score": 50, "indicators": {}}
        score = 50.0
        close = float(candles[-1]["close"])
        if indicators["ema20"] > indicators["ema50"] > indicators["ema200"]:
            score += 22
        elif indicators["ema20"] < indicators["ema50"] < indicators["ema200"]:
            score -= 22
        score += 8 if indicators["macd"] > indicators["macd_signal"] else -8
        score += 6 if 45 <= indicators["rsi"] <= 68 else -6 if indicators["rsi"] > 75 or indicators["rsi"] < 25 else 0
        score += 6 if close > indicators["vwap"] else -6
        score += 4 if indicators["volume_ratio"] >= 1 else -4
        score = round(max(0, min(100, score)), 2)
        trend = "Bullish" if score >= 60 else "Bearish" if score <= 40 else "Neutral"
        return {"trend": trend, "trend_score": score, "indicators": indicators}
