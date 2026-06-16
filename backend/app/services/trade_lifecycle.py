import math
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Any

from app.repositories.base import now_utc
from app.services.indicators import calculate_indicators


REGIME_LABELS = ("Strong Bullish", "Bullish", "Neutral", "Range", "Bearish", "Strong Bearish")
HORIZON_STEPS = {"15m": 4, "1h": 24, "4h": 12, "1d": 7}


class TradeLifecycleEngine:
    def __init__(self, db) -> None:
        self.db = db

    async def build(
        self,
        symbol: str,
        timeframe: str,
        candles: list[dict],
        probabilities: dict,
        model_confidence: float,
        predicted_return_pct: float | None,
        generated_at: datetime,
    ) -> dict:
        current_price = _price(candles[-1].get("close"))
        indicators = calculate_indicators(candles)
        latest = indicators.iloc[-1].to_dict() if not indicators.empty else {}
        predicted_return_pct = float(predicted_return_pct or 0)

        regime = self._market_regime(latest, candles)
        analog = self._historical_analog(indicators, timeframe)
        learning = await self._learning(symbol, timeframe)
        outcome = self._outcome(current_price, predicted_return_pct, analog, latest)
        peak = self._peak(symbol, timeframe, current_price, outcome, analog, generated_at, learning)
        pullback = self._pullback(symbol, timeframe, peak, latest, learning)
        lifecycle = self._lifecycle(current_price, outcome, peak, pullback, latest, timeframe, learning)
        action = self._action(predicted_return_pct, lifecycle, regime, analog, probabilities)
        risk = self._risk(current_price, lifecycle, latest)
        confidence = await self._confidence(model_confidence, analog, regime, candles)
        scores = self._scores(predicted_return_pct, confidence, analog, risk, regime, latest, action)

        return {
            **outcome,
            **regime,
            **analog,
            **peak,
            **pullback,
            **lifecycle,
            **action,
            **risk,
            **confidence,
            **scores,
            "signal": action["recommended_action"],
            "expected_price": outcome["predicted_price"],
            "profit_potential": peak["expected_peak_return_pct"],
            "model_version": "stage11-12-lifecycle-v1",
            "lifecycle_generated_at": generated_at,
        }

    def _outcome(self, current_price: float, predicted_return_pct: float, analog: dict, latest: dict) -> dict:
        analog_return = float(analog.get("historical_avg_return") or 0)
        blended_return = round(predicted_return_pct * 0.65 + analog_return * 0.35, 4)
        if abs(blended_return) < 0.05:
            blended_return = 0.05 if predicted_return_pct >= 0 else -0.05
        atr_pct = _atr_pct(latest, current_price)
        predicted_high_return = max(blended_return, blended_return + atr_pct * 0.7)
        predicted_low_return = min(blended_return, blended_return - atr_pct * 0.7)
        return {
            "predicted_return_pct": blended_return,
            "predicted_change_pct": blended_return,
            "predicted_price": _apply_return(current_price, blended_return),
            "predicted_high": _apply_return(current_price, predicted_high_return),
            "predicted_low": _apply_return(current_price, predicted_low_return),
            "predicted_direction": "UP" if blended_return > 0.15 else "DOWN" if blended_return < -0.15 else "SIDEWAYS",
            "probability_plus_2pct": _probability(blended_return, 2, analog.get("historical_win_rate", 50)),
            "probability_plus_5pct": _probability(blended_return, 5, analog.get("historical_win_rate", 50)),
            "probability_plus_10pct": _probability(blended_return, 10, analog.get("historical_win_rate", 50)),
        }

    def _market_regime(self, latest: dict, candles: list[dict]) -> dict:
        close = _price(latest.get("close") or candles[-1].get("close"))
        ema20 = _price(latest.get("ema20") or close)
        ema50 = _price(latest.get("ema50") or close)
        ema200 = _price(latest.get("ema200") or close)
        trend = float(latest.get("trend_strength") or 0)
        atr_pct = _atr_pct(latest, close)
        volatility = float(latest.get("volatility") or 0)
        structure = _market_structure(candles)
        adx = min(60, abs(trend) * 8 + volatility * 5 + atr_pct * 2)

        if ema20 > ema50 > ema200 and trend > 1.2 and structure >= 0:
            regime = "Strong Bullish"
        elif ema20 > ema50 and trend > 0.25:
            regime = "Bullish"
        elif ema20 < ema50 < ema200 and trend < -1.2 and structure <= 0:
            regime = "Strong Bearish"
        elif ema20 < ema50 and trend < -0.25:
            regime = "Bearish"
        elif volatility < 1.2 and abs(trend) < 0.35:
            regime = "Range"
        else:
            regime = "Neutral"

        directional_score = {"Strong Bullish": 95, "Bullish": 75, "Neutral": 52, "Range": 48, "Bearish": 28, "Strong Bearish": 8}[regime]
        confidence = round(max(5, min(95, abs(trend) * 14 + adx * 0.8 + min(25, abs(structure) * 12))), 2)
        return {
            "market_regime": regime,
            "market_regime_score": directional_score,
            "regime_confidence": confidence,
            "regime_reliability": confidence,
            "regime_inputs": {
                "ema20": round(ema20, 8),
                "ema50": round(ema50, 8),
                "ema200": round(ema200, 8),
                "adx": round(adx, 4),
                "atr_pct": round(atr_pct, 4),
                "trend_strength": round(trend, 4),
                "volatility": round(volatility, 4),
                "market_structure": round(structure, 4),
            },
        }

    def _historical_analog(self, indicators, timeframe: str) -> dict:
        if indicators.empty or len(indicators) < 40:
            return _empty_analog()
        features = ["rsi", "macd", "atr", "ema20", "ema50", "ema200", "volume_ratio", "trend_strength", "volatility"]
        horizon = min(HORIZON_STEPS.get(timeframe, 12), max(1, len(indicators) // 4))
        latest = indicators.iloc[-1]
        candidates = []
        usable = indicators.iloc[:-horizon]
        for index, row in usable.iterrows():
            distance = 0.0
            used = 0
            for feature in features:
                series = usable[feature].astype(float)
                spread = float(series.std() or 1)
                distance += ((float(row[feature]) - float(latest[feature])) / spread) ** 2
                used += 1
            similarity = max(0, 100 - math.sqrt(distance / max(1, used)) * 18)
            current = float(row["close"] or 0)
            future = indicators.iloc[min(len(indicators) - 1, int(index) + horizon)]
            future_slice = indicators.iloc[int(index) + 1 : min(len(indicators), int(index) + horizon + 1)]
            if current <= 0 or future_slice.empty:
                continue
            future_close = float(future["close"] or current)
            max_high = float(future_slice["high"].max())
            min_low = float(future_slice["low"].min())
            candidates.append({
                "similarity_score": round(similarity, 4),
                "return_pct": (future_close / current - 1) * 100,
                "max_return_pct": (max_high / current - 1) * 100,
                "drawdown_pct": min(0, (min_low / current - 1) * 100),
            })
        top = sorted(candidates, key=lambda item: item["similarity_score"], reverse=True)[:50]
        if not top:
            return _empty_analog()
        win_rate = len([row for row in top if row["return_pct"] > 0]) / len(top) * 100
        avg_return = mean([row["return_pct"] for row in top])
        max_return = max(row["max_return_pct"] for row in top)
        avg_drawdown = mean([row["drawdown_pct"] for row in top])
        similarity = mean([row["similarity_score"] for row in top])
        return {
            "historical_analogs": top,
            "historical_win_rate": round(win_rate, 2),
            "historical_avg_return": round(avg_return, 4),
            "historical_max_return": round(max_return, 4),
            "historical_avg_drawdown": round(avg_drawdown, 4),
            "similarity_score": round(similarity, 2),
            "pattern_confidence": round(max(1, min(95, similarity * 0.7 + win_rate * 0.3)), 2),
        }

    def _peak(self, symbol: str, timeframe: str, current_price: float, outcome: dict, analog: dict, generated_at: datetime, learning: dict) -> dict:
        peak_return = max(float(outcome["predicted_return_pct"]), float(analog.get("historical_max_return") or 0) * 0.55)
        if peak_return <= 0:
            peak_return = max(0.05, abs(float(outcome["predicted_return_pct"])) * 0.35)
        timing_hours = abs(float((learning.get("timing") or {}).get("average_timing_error_minutes") or 0)) / 60
        steps = max(1, min(HORIZON_STEPS.get(timeframe, 6), 8))
        if timing_hours > 0:
            steps = max(1, round(steps + min(3, timing_hours / max(1, _timeframe_hours(timeframe)))))
        peak_time = generated_at + _timeframe_delta(timeframe, steps)
        probability = round(max(1, min(95, float(analog.get("pattern_confidence") or 50) * 0.45 + float(outcome.get("probability_plus_2pct") or 0) * 0.35 + 20)), 2)
        return {
            "expected_peak_price": _apply_return(current_price, peak_return),
            "expected_peak_time": _iso(peak_time),
            "expected_peak_return_pct": round(peak_return, 4),
            "peak_probability": probability,
        }

    def _pullback(self, symbol: str, timeframe: str, peak: dict, latest: dict, learning: dict) -> dict:
        peak_price = float(peak["expected_peak_price"])
        pullback_pct = max(0.25, min(12, abs(float(latest.get("volatility") or 0)) * 0.7 + _atr_pct(latest, peak_price) * 1.2))
        pullback_error = abs(float((learning.get("pullback") or {}).get("pullback_price_error_pct") or 0))
        if pullback_error:
            pullback_pct = max(0.25, min(12, pullback_pct * (1 + min(0.25, pullback_error / 100))))
        peak_time = _parse_time(peak["expected_peak_time"]) or now_utc()
        pullback_time = peak_time + _timeframe_delta(timeframe, max(1, min(HORIZON_STEPS.get(timeframe, 6) // 2, 5)))
        return {
            "expected_pullback_price": _apply_return(peak_price, -pullback_pct),
            "expected_pullback_time": _iso(pullback_time),
            "pullback_probability": round(max(1, min(95, float(peak.get("peak_probability") or 50) * 0.72)), 2),
            "expected_reentry_price": _apply_return(peak_price, -pullback_pct),
            "expected_reentry_time": _iso(pullback_time),
        }

    def _lifecycle(self, current_price: float, outcome: dict, peak: dict, pullback: dict, latest: dict, timeframe: str, learning: dict) -> dict:
        atr_pct = _atr_pct(latest, current_price)
        expected_drawdown = max(0.25, min(20, abs(float(outcome["predicted_return_pct"])) * 0.35 + atr_pct * 1.4))
        target_learning = learning.get("target") or {}
        if target_learning.get("average_drawdown"):
            expected_drawdown = max(expected_drawdown, min(20, abs(float(target_learning.get("average_drawdown") or 0))))
        entry_low = _apply_return(current_price, -min(1.5, atr_pct * 0.4))
        entry_high = _apply_return(current_price, min(1.5, atr_pct * 0.25))
        stop_loss = _apply_return(current_price, -expected_drawdown)
        peak_return = float(peak["expected_peak_return_pct"])
        reliability = float(target_learning.get("target_reliability_score") or 50)
        target_scale = 0.85 + min(0.3, reliability / 250)
        target_1 = _apply_return(current_price, max(0.1, peak_return * 0.35 * target_scale))
        target_2 = _apply_return(current_price, max(0.2, peak_return * 0.65 * target_scale))
        target_3 = float(peak["expected_peak_price"])
        peak_time = _parse_time(peak["expected_peak_time"])
        hours = ((peak_time - now_utc()).total_seconds() / 3600) if peak_time else 0
        return {
            "entry_price": current_price,
            "entry_zone": {"low": entry_low, "high": entry_high},
            "stop_loss": stop_loss,
            "target_1": round(target_1, 8),
            "target_2": round(target_2, 8),
            "target_3": round(target_3, 8),
            "take_profit_1": round(target_1, 8),
            "take_profit_2": round(target_2, 8),
            "take_profit_3": round(target_3, 8),
            "targets": [round(target_1, 8), round(target_2, 8), round(target_3, 8)],
            "expected_drawdown_pct": round(expected_drawdown, 4),
            "expected_drawdown": round(expected_drawdown, 4),
            "holding_duration": _duration(hours),
            "sell_price": round(target_3, 8),
            "sell_time": peak["expected_peak_time"],
            "rebuy_price": pullback["expected_reentry_price"],
            "rebuy_time": pullback["expected_reentry_time"],
        }

    def _action(self, predicted_return_pct: float, lifecycle: dict, regime: dict, analog: dict, probabilities: dict) -> dict:
        risk_reward = _risk_reward(lifecycle["entry_price"], lifecycle["target_2"], lifecycle["stop_loss"])
        win_rate = float(analog.get("historical_win_rate") or 50)
        peak_return = float(lifecycle.get("expected_peak_return_pct") or 0)
        regime_score = float(regime.get("market_regime_score") or 50)
        if predicted_return_pct >= 1.2 and risk_reward >= 1.4 and win_rate >= 52 and regime_score >= 45:
            action = "BUY NOW"
        elif predicted_return_pct >= 0.25 and risk_reward >= 1:
            action = "WAIT"
        elif predicted_return_pct <= -2:
            action = "SELL"
        elif predicted_return_pct <= -0.5:
            action = "TAKE PROFIT"
        elif abs(predicted_return_pct) < 0.25:
            action = "HOLD"
        else:
            action = "BUY AGAIN"
        confidence = max(probabilities.values()) if probabilities else 50
        return {"recommended_action": action, "action_confidence": round(max(1, min(95, confidence * 0.55 + win_rate * 0.25 + risk_reward * 8)), 2)}

    def _risk(self, current_price: float, lifecycle: dict, latest: dict) -> dict:
        rr = _risk_reward(current_price, lifecycle["target_2"], lifecycle["stop_loss"])
        volatility = max(0, min(100, float(latest.get("volatility") or 0) * 18 + _atr_pct(latest, current_price) * 10))
        drawdown = float(lifecycle["expected_drawdown_pct"])
        risk_score = round(max(1, min(100, volatility * 0.45 + drawdown * 3 + max(0, 2 - rr) * 18)), 2)
        risk_class = "Low Risk" if risk_score < 30 else "Moderate Risk" if risk_score < 55 else "High Risk" if risk_score < 78 else "Speculative"
        return {
            "risk_reward_ratio": f"1:{round(rr, 2)}",
            "risk_reward_value": round(rr, 4),
            "volatility_score": round(volatility, 2),
            "risk_score": risk_score,
            "risk_classification": risk_class,
            "probability_stop_loss": round(max(1, min(95, risk_score * 0.75)), 2),
            "probability_target1": round(max(1, min(95, 95 - risk_score * 0.45)), 2),
            "probability_target2": round(max(1, min(95, 82 - risk_score * 0.38)), 2),
            "probability_target3": round(max(1, min(95, 68 - risk_score * 0.32)), 2),
        }

    async def _confidence(self, model_confidence: float, analog: dict, regime: dict, candles: list[dict]) -> dict:
        calibration = await self.db.confidence_calibration.find_one({"source_type": "live"}, sort=[("created_at", -1)]) or {}
        weights_doc = await self.db.lifecycle_model_weights.find_one({"scope": "lifecycle_confidence"}, sort=[("created_at", -1)]) or {}
        weights = weights_doc.get("weights") or {}
        reliability = float(calibration.get("confidence_reliability") or 60)
        data_quality = _data_quality(candles)
        score = (
            float(model_confidence or 0) * float(weights.get("model_confidence", 0.40))
            + float(analog.get("historical_win_rate") or 50) * float(weights.get("historical_win_rate", 0.25))
            + float(analog.get("pattern_confidence") or 50) * float(weights.get("pattern_confidence", 0.15))
            + float(regime.get("regime_reliability") or 50) * float(weights.get("regime_reliability", 0.10))
            + data_quality * float(weights.get("data_quality", 0.10))
        )
        confidence = round(max(1, min(95, score)), 2)
        return {
            "confidence_score": confidence,
            "confidence": confidence,
            "probability_of_success": confidence,
            "confidence_components": {
                "model_confidence": round(float(model_confidence or 0), 2),
                "historical_win_rate": float(analog.get("historical_win_rate") or 0),
                "pattern_confidence": float(analog.get("pattern_confidence") or 0),
                "regime_reliability": float(regime.get("regime_reliability") or 0),
                "data_quality": data_quality,
                "calibration_reliability": reliability,
                "adaptive_weights": weights,
            },
        }

    async def _learning(self, symbol: str, timeframe: str) -> dict:
        async def latest(scope: str, key: str) -> dict:
            return await self.db.adaptive_learning_stats.find_one({"scope": scope, "key": key}, sort=[("created_at", -1)]) or {}

        return {
            "coin": await latest("coin_learning_latest", symbol),
            "timeframe": await latest("timeframe_learning_latest", timeframe),
            "coin_timeframe": await latest("coin_timeframe_learning_latest", f"{symbol}:{timeframe}"),
            "target": await latest("target_learning_latest", "system"),
            "peak": await latest("peak_learning_latest", "system"),
            "pullback": await latest("pullback_learning_latest", "system"),
            "timing": await latest("timing_learning_latest", "system"),
        }

    def _scores(self, expected_return: float, confidence: dict, analog: dict, risk: dict, regime: dict, latest: dict, action: dict) -> dict:
        expected_return_score = max(0, min(100, abs(expected_return) * 8))
        confidence_score = float(confidence["confidence_score"])
        win_rate = float(analog.get("historical_win_rate") or 50)
        rr_score = max(0, min(100, float(risk.get("risk_reward_value") or 0) * 28))
        momentum = max(0, min(100, 50 + float(latest.get("trend_strength") or 0) * 12))
        volume = max(0, min(100, float(latest.get("volume_ratio") or 1) * 35))
        regime_score = float(regime.get("market_regime_score") or 50)
        similarity = float(analog.get("similarity_score") or 50)
        opportunity = (
            expected_return_score * 0.25
            + confidence_score * 0.20
            + win_rate * 0.15
            + rr_score * 0.15
            + momentum * 0.10
            + volume * 0.05
            + regime_score * 0.05
            + similarity * 0.05
        )
        buy_score = opportunity if action["recommended_action"] in {"BUY NOW", "BUY AGAIN", "WAIT"} else opportunity * 0.45
        sell_score = opportunity if action["recommended_action"] in {"SELL", "TAKE PROFIT"} else max(0, 100 - opportunity)
        reentry_score = max(0, min(100, buy_score * 0.65 + float(risk.get("pullback_probability", 50)) * 0.35))
        return {
            "opportunity_score_v2": round(max(0, min(100, opportunity)), 2),
            "overall_opportunity_score": round(max(0, min(100, opportunity)), 2),
            "buy_score": round(max(0, min(100, buy_score)), 2),
            "sell_score": round(max(0, min(100, sell_score)), 2),
            "reentry_score": round(max(0, min(100, reentry_score)), 2),
        }


def _empty_analog() -> dict:
    return {
        "historical_analogs": [],
        "historical_win_rate": 50,
        "historical_avg_return": 0,
        "historical_max_return": 0,
        "historical_avg_drawdown": 0,
        "similarity_score": 50,
        "pattern_confidence": 50,
    }


def _price(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def _apply_return(price: float, return_pct: float) -> float:
    return round(price * (1 + return_pct / 100), 8) if price > 0 else 0


def _probability(predicted_return: float, threshold: float, base: Any) -> float:
    base_rate = _price(base)
    edge = (predicted_return - threshold) * 9
    return round(max(1, min(95, base_rate * 0.55 + 35 + edge)), 2)


def _atr_pct(latest: dict, close: float) -> float:
    atr = _price(latest.get("atr"))
    return abs(atr / close * 100) if close > 0 else 0


def _market_structure(candles: list[dict]) -> float:
    if len(candles) < 12:
        return 0
    recent = candles[-12:]
    older = candles[-24:-12] if len(candles) >= 24 else candles[:12]
    recent_high = max(_price(row.get("high")) for row in recent)
    recent_low = min(_price(row.get("low")) for row in recent)
    older_high = max(_price(row.get("high")) for row in older)
    older_low = min(_price(row.get("low")) for row in older)
    score = 0
    if recent_high > older_high:
        score += 1
    if recent_low > older_low:
        score += 1
    if recent_high < older_high:
        score -= 1
    if recent_low < older_low:
        score -= 1
    return score / 2


def _timeframe_delta(timeframe: str, steps: int) -> timedelta:
    if timeframe == "15m":
        return timedelta(minutes=15 * steps)
    if timeframe == "4h":
        return timedelta(hours=4 * steps)
    if timeframe == "1d":
        return timedelta(days=steps)
    return timedelta(hours=steps)


def _timeframe_hours(timeframe: str) -> float:
    if timeframe == "15m":
        return 0.25
    if timeframe == "4h":
        return 4
    if timeframe == "1d":
        return 24
    return 1


def _risk_reward(entry: float, target: float, stop: float) -> float:
    risk = abs(entry - stop)
    reward = abs(target - entry)
    return reward / risk if risk > 0 else 0


def _data_quality(candles: list[dict]) -> float:
    if not candles:
        return 0
    completeness = min(100, len(candles) / 240 * 100)
    valid = len([row for row in candles if _price(row.get("close")) > 0 and row.get("timestamp")])
    return round(max(0, min(100, completeness * 0.65 + valid / len(candles) * 35)), 2)


def _duration(hours: float) -> str:
    if hours <= 0:
        return ""
    if hours < 24:
        return f"{round(hours, 1)} Hours"
    return f"{round(hours / 24, 1)} Days"


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
