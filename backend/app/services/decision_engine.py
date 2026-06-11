from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DecisionThresholds:
    low_confidence: float = 85
    medium_confidence: float = 75
    high_confidence: float = 65
    minimum_net_profit: float = 2
    minimum_stop_distance: float = 0.25


class InstitutionalDecisionEngine:
    def __init__(self, thresholds: DecisionThresholds | None = None):
        self.thresholds = thresholds or DecisionThresholds()

    def decide(self, payload: dict[str, Any]) -> dict[str, Any]:
        scores = payload["scores"]
        profitability = payload["profitability"]
        risk = payload["risk"]
        technical = payload["technical"]
        volume = payload["volume"]
        market = payload["market"]
        confidence = self.confidence(scores)
        side = self.side(technical, volume)
        rr = float(profitability["risk_reward"])
        net_profit = float(profitability["net_profit_percent"])
        risk_category = self.risk_category(confidence, rr, technical, volume, risk)
        rejection = self.rejection_reason(confidence, rr, net_profit, technical, volume, risk, market, profitability, risk_category)
        if rejection:
            return {"status": "NO_TRADE", "reason": rejection, "confidence_score": round(confidence, 2)}
        return {
            "status": "TRADE",
            "coin": market["coin"],
            "pair": market["pair"],
            "signal_type": side,
            "risk_category": risk_category,
            "current_price": round(float(market["current_price"]), 8),
            "entry_price": round(float(profitability["entry_price"]), 8),
            "stop_loss": round(float(profitability["stop_loss"]), 8),
            "take_profit_1": round(float(profitability["take_profit_1"]), 8),
            "take_profit_2": round(float(profitability["take_profit_2"]), 8),
            "take_profit_3": round(float(profitability["take_profit_3"]), 8),
            "risk_reward_ratio": f"1:{rr:.2f}",
            "confidence_score": round(confidence, 2),
            "probability_of_success": self.probability(confidence, risk),
            "estimated_duration": self.duration(technical, risk),
            "gross_profit_percent": round(float(profitability["gross_profit_percent"]), 2),
            "total_fees_percent": round(float(profitability["total_fees_percent"]), 2),
            "tds_percent": round(float(profitability["tds_percent"]), 2),
            "slippage_percent": round(float(profitability["slippage_percent"]), 2),
            "net_profit_percent": round(net_profit, 2),
            "signal_strength": self.signal_strength(confidence),
            "technical_score": round(float(scores["technical_score"]), 2),
            "volume_score": round(float(scores["volume_score"]), 2),
            "sentiment_score": round(float(scores["sentiment_score"]), 2),
            "onchain_score": round(float(scores["onchain_score"]), 2),
            "risk_score": round(float(scores["risk_score"]), 2),
            "profitability_score": round(float(scores["profitability_score"]), 2),
            "reasoning": self.reasoning(payload, side),
            "risks": self.risks(payload),
            "validation_passed": True,
        }

    def confidence(self, scores: dict[str, float]) -> float:
        return (
            float(scores["technical_score"]) * 0.35
            + float(scores["volume_score"]) * 0.20
            + float(scores["sentiment_score"]) * 0.15
            + float(scores["onchain_score"]) * 0.10
            + float(scores["profitability_score"]) * 0.10
            + float(scores["risk_score"]) * 0.10
        )

    def side(self, technical: dict[str, Any], volume: dict[str, Any]) -> str:
        trend = str(technical["trend_direction"]).upper()
        pressure = str(volume["buy_sell_pressure"]).upper()
        if trend == "DOWN" and pressure == "SELL":
            return "SELL"
        if trend == "UP" and pressure == "BUY":
            return "BUY"
        return "HOLD"

    def risk_category(self, confidence: float, rr: float, technical: dict[str, Any], volume: dict[str, Any], risk: dict[str, Any]) -> str | None:
        strong_trend = bool(technical["strong_trend_confirmation"])
        trend = bool(technical["trend_confirmation"])
        volume_ok = bool(volume["volume_confirmation"])
        low_volatility = str(risk["volatility_level"]).upper() == "LOW"
        setup = str(technical["setup_type"]).upper()
        if confidence >= self.thresholds.low_confidence and strong_trend and volume_ok and rr >= 2 and low_volatility:
            return "LOW_RISK"
        if confidence >= self.thresholds.medium_confidence and trend and volume_ok and rr >= 3:
            return "MEDIUM_RISK"
        if confidence >= self.thresholds.high_confidence and setup in {"BREAKOUT", "REVERSAL"} and rr >= 5:
            return "HIGH_RISK"
        return None

    def rejection_reason(
        self,
        confidence: float,
        rr: float,
        net_profit: float,
        technical: dict[str, Any],
        volume: dict[str, Any],
        risk: dict[str, Any],
        market: dict[str, Any],
        profitability: dict[str, Any],
        risk_category: str | None,
    ) -> str | None:
        if risk_category is None:
            return "Confidence, trend, volume, and risk reward do not meet an approved risk category"
        if confidence < self.thresholds.high_confidence:
            return "Confidence below threshold"
        if rr <= 0:
            return "Risk reward invalid"
        if not technical["trend_confirmation"]:
            return "Trend confirmation absent"
        if not volume["volume_confirmation"]:
            return "Volume confirmation absent"
        if float(profitability["stop_distance_percent"]) < self.thresholds.minimum_stop_distance:
            return "Stop loss too close"
        if str(risk["liquidity_risk"]).upper() == "HIGH":
            return "Liquidity risk high"
        if str(risk["manipulation_risk"]).upper() == "HIGH":
            return "Manipulation risk high"
        if net_profit <= self.thresholds.minimum_net_profit:
            return "Net expected profit after fees is below 2%"
        if not market["exchange_volume_sufficient"]:
            return "Exchange volume insufficient"
        return None

    def probability(self, confidence: float, risk: dict[str, Any]) -> float:
        penalty = {"LOW": 0, "MEDIUM": 4, "HIGH": 10}.get(str(risk["drawdown_risk"]).upper(), 6)
        return round(max(1, min(99, confidence - penalty)), 2)

    def duration(self, technical: dict[str, Any], risk: dict[str, Any]) -> str:
        strength = float(technical["trend_strength"])
        volatility = str(risk["volatility_level"]).upper()
        if volatility == "HIGH":
            return "6-12 Hours"
        if strength >= 70:
            return "12-24 Hours"
        if strength >= 45:
            return "1-3 Days"
        return "3-7 Days"

    def signal_strength(self, confidence: float) -> str:
        if confidence >= 90:
            return "VERY_STRONG"
        if confidence >= 80:
            return "STRONG"
        if confidence >= 70:
            return "MODERATE"
        return "WEAK"

    def reasoning(self, payload: dict[str, Any], side: str) -> list[str]:
        technical = payload["technical"]
        volume = payload["volume"]
        sentiment = payload["sentiment"]
        onchain = payload["onchain"]
        risk = payload["risk"]
        profitability = payload["profitability"]
        return [
            f"{side} selected because trend direction is {technical['trend_direction']} with technical score {payload['scores']['technical_score']}.",
            f"Technical support: RSI {technical['rsi']}, MACD {technical['macd_state']}, EMA state {technical['ema_state']}, trend strength {technical['trend_strength']}.",
            f"Volume support: pressure {volume['buy_sell_pressure']}, order book imbalance {volume['order_book_imbalance']}, smart money flow {volume['smart_money_flow']}.",
            f"Sentiment support: fear and greed {sentiment['fear_greed_index']}, news {sentiment['news_sentiment']}, community momentum {sentiment['community_momentum']}.",
            f"On-chain support: exchange flow {onchain['exchange_flow']}, active addresses {onchain['active_addresses']}, accumulation {onchain['wallet_accumulation']}.",
            f"Risk considered: volatility {risk['volatility_level']}, liquidity risk {risk['liquidity_risk']}, drawdown risk {risk['drawdown_risk']}, manipulation risk {risk['manipulation_risk']}.",
            f"Expected duration is based on trend strength and volatility; primary target has net profit {profitability['net_profit_percent']}% after fees.",
            "Alternative trades rejected because the final decision layer only approves the highest-confidence direction passing all validations.",
        ]

    def risks(self, payload: dict[str, Any]) -> list[str]:
        risk = payload["risk"]
        profitability = payload["profitability"]
        return [
            f"Maximum drawdown risk: {risk['maximum_drawdown_percent']}%",
            f"Volatility level: {risk['volatility_level']}",
            f"Liquidity risk: {risk['liquidity_risk']}",
            f"Manipulation risk: {risk['manipulation_risk']}",
            f"Slippage estimate: {profitability['slippage_percent']}%",
        ]
