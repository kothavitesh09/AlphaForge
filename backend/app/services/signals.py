import logging
from app.repositories.base import MongoRepository, now_utc
from app.services.decision_engine import InstitutionalDecisionEngine
from app.services.indicators import calculate_indicators, order_book_imbalance
from app.services.performance_engine import PerformanceEngine
from app.services.prediction import PredictionService


logger = logging.getLogger(__name__)


class SignalService:
    def __init__(self, db):
        self.signals = MongoRepository(db, "signals")
        self.predictions = MongoRepository(db, "predictions")
        self.predictor = PredictionService()
        self.decider = InstitutionalDecisionEngine()

    async def generate(self, symbol: str, candles: list[dict], order_book: dict, sentiment: dict) -> dict:
        analysis = self.analysis_payload(symbol, candles, order_book, sentiment)
        decision = self.decider.decide(analysis)
        record = self.record_from_decision(symbol, decision, analysis)
        saved_signal = await self.signals.insert(record)
        logger.info("Signal Generated symbol=%s signal=%s confidence=%s", symbol.upper(), saved_signal.get("signal"), saved_signal.get("confidence"))
        await PerformanceEngine(self.signals.collection.database).ensure_simulated_trade(saved_signal)
        if decision["status"] == "TRADE":
            await self.predictions.insert({"symbol": symbol.upper(), "signal_id": saved_signal["id"], **decision, "created_at": now_utc()})
        return saved_signal

    def analysis_payload(self, symbol: str, candles: list[dict], order_book: dict, sentiment: dict) -> dict:
        df = calculate_indicators(candles)
        if df.empty:
            raise ValueError("No candle data available")
        latest = df.iloc[-1]
        imbalance = order_book_imbalance(order_book)
        score = 50.0
        reasons: list[str] = []
        score += self._score_rsi(float(latest["rsi"]), reasons)
        score += self._score_macd(float(latest["macd"]), float(latest["macd_signal"]), reasons)
        score += self._score_emas(float(latest["ema20"]), float(latest["ema50"]), float(latest["ema200"]), reasons)
        score += self._score_bollinger(float(latest["close"]), float(latest["bb_lower"]), float(latest["bb_upper"]), reasons)
        score += self._score_volume(float(latest["volume_ratio"]), reasons)
        score += max(-8, min(8, imbalance * 16))
        score += max(-6, min(6, float(sentiment.get("score", 0)) * 6))
        score = round(max(0, min(100, score)), 2)
        try:
            prediction = self.predictor.train_predict(candles, order_book, sentiment)
        except ValueError as exc:
            prediction = {
                "signal": "HOLD",
                "model_direction": "HOLD",
                "buy_probability": 0,
                "sell_probability": 0,
                "hold_probability": 100,
                "confidence": 0,
                "expected_move": "No approved setup",
                "expected_window": "No trade",
                "validation_accuracy": 0,
                "model_warning": str(exc),
            }
        if prediction["buy_probability"] > 70:
            signal = "BUY"
        elif prediction["sell_probability"] > 70:
            signal = "SELL"
        else:
            signal = "BUY" if score >= 60 else "SELL" if score <= 39 else "HOLD"
        risk = self._risk(float(latest["volatility"]), abs(float(latest["trend_strength"])), abs(imbalance))
        current = float(latest["close"])
        bullish = signal == "BUY"
        atr_pct = 0 if current <= 0 else float(latest["atr"]) / current * 100
        stop_distance = max(atr_pct * 1.2, 0.6)
        target_distance = max(stop_distance * 3, 2.5)
        entry = current
        stop = entry * (1 - stop_distance / 100) if bullish else entry * (1 + stop_distance / 100)
        tp1 = entry * (1 + target_distance / 100) if bullish else entry * (1 - target_distance / 100)
        tp2 = entry * (1 + target_distance * 1.5 / 100) if bullish else entry * (1 - target_distance * 1.5 / 100)
        tp3 = entry * (1 + target_distance * 2 / 100) if bullish else entry * (1 - target_distance * 2 / 100)
        fees = 0.7
        tds = 1.0
        slippage = 0.25 if abs(imbalance) > 0.15 else 0.15
        total_fees = fees + tds + slippage
        net_profit = target_distance - total_fees
        technical_score = score
        volume_score = round(max(0, min(100, 50 + float(latest["volume_ratio"]) * 12 + imbalance * 30)), 2)
        sentiment_score = round(max(0, min(100, 50 + float(sentiment.get("score", 0)) * 50)), 2)
        onchain_score = 50.0
        risk_score = {"Low": 88.0, "Medium": 72.0, "High": 48.0}[risk]
        profitability_score = round(max(0, min(100, 50 + net_profit * 8)), 2)
        return {
            "market": {
                "coin": symbol.split("_")[0].upper(),
                "pair": symbol.upper(),
                "current_price": current,
                "exchange_volume_sufficient": float(latest["volume"]) > 0,
            },
            "technical": {
                "rsi": round(float(latest["rsi"]), 2),
                "macd_state": "BULLISH" if float(latest["macd"]) > float(latest["macd_signal"]) else "BEARISH",
                "ema_state": "BULLISH" if float(latest["ema20"]) > float(latest["ema50"]) else "BEARISH",
                "trend_direction": "UP" if signal == "BUY" else "DOWN" if signal == "SELL" else "SIDEWAYS",
                "trend_strength": round(abs(float(latest["trend_strength"])) * 10, 2),
                "trend_confirmation": signal in {"BUY", "SELL"} and score >= 60,
                "strong_trend_confirmation": signal in {"BUY", "SELL"} and score >= 75,
                "setup_type": "BREAKOUT" if float(latest["volume_ratio"]) > 1.5 else "TREND",
            },
            "volume": {
                "volume_spike_detection": float(latest["volume_ratio"]) > 1.5,
                "buy_sell_pressure": "BUY" if imbalance >= 0 else "SELL",
                "order_book_imbalance": round(imbalance, 4),
                "liquidity_zones": "AVAILABLE" if order_book.get("bids") and order_book.get("asks") else "THIN",
                "whale_activity": "UNCONFIRMED",
                "smart_money_flow": "POSITIVE" if imbalance > 0.05 else "NEGATIVE" if imbalance < -0.05 else "NEUTRAL",
                "volume_confirmation": float(latest["volume_ratio"]) >= 0.7 and abs(imbalance) < 0.75,
            },
            "sentiment": {
                "fear_greed_index": "NEUTRAL",
                "news_sentiment": sentiment.get("news", 0),
                "reddit_sentiment": sentiment.get("social", 0),
                "twitter_x_sentiment": sentiment.get("social", 0),
                "community_momentum": "NEUTRAL",
            },
            "onchain": {
                "exchange_flow": "UNKNOWN",
                "active_addresses": "UNKNOWN",
                "large_transactions": "UNKNOWN",
                "wallet_accumulation": "UNKNOWN",
                "token_unlock_events": "UNKNOWN",
            },
            "risk": {
                "volatility_level": risk.upper(),
                "liquidity_risk": "LOW" if order_book.get("bids") and order_book.get("asks") else "HIGH",
                "drawdown_risk": risk.upper(),
                "manipulation_risk": "HIGH" if abs(imbalance) > 0.85 else "MEDIUM" if abs(imbalance) > 0.55 else "LOW",
                "maximum_drawdown_percent": round(stop_distance, 2),
            },
            "profitability": {
                "entry_price": entry,
                "stop_loss": stop,
                "take_profit_1": tp1,
                "take_profit_2": tp2,
                "take_profit_3": tp3,
                "risk_reward": round(target_distance / stop_distance, 2) if stop_distance else 0,
                "gross_profit_percent": round(target_distance, 2),
                "total_fees_percent": round(total_fees, 2),
                "tds_percent": tds,
                "slippage_percent": slippage,
                "net_profit_percent": round(net_profit, 2),
                "stop_distance_percent": round(stop_distance, 2),
            },
            "scores": {
                "technical_score": technical_score,
                "volume_score": volume_score,
                "sentiment_score": sentiment_score,
                "onchain_score": onchain_score,
                "risk_score": risk_score,
                "profitability_score": profitability_score,
            },
            "legacy": {
                "signal": signal,
                "score": score,
                "confidence": prediction["confidence"],
                "explanation": reasons or ["Mixed technical conditions"],
                "expected_move": prediction["expected_move"],
                "expected_window": prediction["expected_window"],
                "risk": risk,
            },
        }

    def record_from_decision(self, symbol: str, decision: dict, analysis: dict) -> dict:
        legacy = analysis["legacy"]
        if decision["status"] == "TRADE":
            return {
                "symbol": symbol.upper(),
                "signal": decision["signal_type"],
                "action": decision["signal_type"],
                "score": decision["technical_score"],
                "confidence": decision["confidence_score"],
                "explanation": decision["reasoning"],
                "expected_move": f"{decision['net_profit_percent']}% net",
                "expected_window": decision["estimated_duration"],
                "expected_time": decision["estimated_duration"],
                "risk": decision["risk_category"],
                "entry": decision["entry_price"],
                "target": decision["take_profit_1"],
                "stop_loss": decision["stop_loss"],
                "expected_profit": decision["net_profit_percent"],
                "risk_reward": decision["risk_reward_ratio"],
                "decision": decision,
                "analysis": analysis,
                "created_at": now_utc(),
            }
        return {
            "symbol": symbol.upper(),
            "signal": "NO_TRADE",
            "action": "HOLD",
            "score": legacy["score"],
            "confidence": decision["confidence_score"],
            "explanation": [decision["reason"]],
            "expected_move": "No approved setup",
            "expected_window": "No trade",
            "expected_time": "No trade",
            "risk": "NO_TRADE",
            "entry": analysis["profitability"]["entry_price"],
            "target": analysis["profitability"]["take_profit_1"],
            "stop_loss": analysis["profitability"]["stop_loss"],
            "expected_profit": 0,
            "risk_reward": "0",
            "decision": decision,
            "analysis": analysis,
            "created_at": now_utc(),
        }

    async def latest(self, symbol: str | None = None, limit: int = 50) -> list[dict]:
        query = {"symbol": symbol.upper()} if symbol else {}
        return await self.signals.find_many(query, limit=limit, sort=[("created_at", -1)])

    def _score_rsi(self, rsi: float, reasons: list[str]) -> float:
        if rsi < 30:
            reasons.append("RSI oversold")
            return 10
        if rsi > 70:
            reasons.append("RSI overbought")
            return -10
        return 0

    def _score_macd(self, macd: float, signal: float, reasons: list[str]) -> float:
        if macd > signal:
            reasons.append("Bullish MACD cross")
            return 8
        reasons.append("Bearish MACD pressure")
        return -8

    def _score_emas(self, ema20: float, ema50: float, ema200: float, reasons: list[str]) -> float:
        if ema20 > ema50 > ema200:
            reasons.append("Strong uptrend")
            return 14
        if ema20 < ema50 < ema200:
            reasons.append("Strong downtrend")
            return -14
        return 0

    def _score_bollinger(self, close: float, lower: float, upper: float, reasons: list[str]) -> float:
        if close <= lower:
            reasons.append("Price near lower Bollinger Band")
            return 6
        if close >= upper:
            reasons.append("Price near upper Bollinger Band")
            return -6
        return 0

    def _score_volume(self, ratio: float, reasons: list[str]) -> float:
        if ratio > 1.8:
            reasons.append("Volume spike")
            return 5
        if ratio < 0.6:
            reasons.append("Weak volume")
            return -4
        return 0

    def _risk(self, volatility: float, trend_strength: float, imbalance: float) -> str:
        score = volatility * 0.6 + max(0, 3 - trend_strength) + (1 - min(imbalance, 1)) * 2
        if score < 3:
            return "Low"
        if score < 7:
            return "Medium"
        return "High"
