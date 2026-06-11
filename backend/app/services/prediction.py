from datetime import timedelta
import numpy as np
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split
from xgboost import XGBClassifier
from app.repositories.base import now_utc
from app.services.indicators import calculate_indicators, order_book_imbalance


LABELS = ["SELL", "HOLD", "BUY"]


class PredictionService:
    def feature_columns(self) -> list[str]:
        return ["rsi", "macd", "volume_ratio", "trend_strength", "volatility", "atr", "order_book_imbalance", "sentiment_score"]

    def labels(self, df):
        future_return = df["close"].shift(-12) / df["close"] - 1
        return np.select([future_return < -0.03, future_return > 0.03], [0, 2], default=1)

    def train_predict(self, candles: list[dict], order_book: dict, sentiment: dict) -> dict:
        df = calculate_indicators(candles)
        if len(df) < 60:
            raise ValueError("At least 60 candles are required for prediction")
        df["order_book_imbalance"] = order_book_imbalance(order_book)
        df["sentiment_score"] = float(sentiment.get("score", 0))
        features = df[self.feature_columns()].replace([np.inf, -np.inf], 0).fillna(0)
        y = self.labels(df)
        valid = ~np.isnan(y)
        x_train, x_val, y_train, y_val = train_test_split(features[valid], y[valid], test_size=0.25, shuffle=False)
        if len(set(y_train.tolist())) < 2:
            probs = self.rule_probabilities(df.iloc[-1], float(order_book_imbalance(order_book)), float(sentiment.get("score", 0)))
            validation_accuracy = 0.0
        else:
            model = XGBClassifier(n_estimators=80, max_depth=3, learning_rate=0.08, objective="multi:softprob", eval_metric="mlogloss")
            model.fit(x_train, y_train)
            predicted = model.predict(x_val) if len(y_val) else []
            probabilities = dict(zip(model.classes_.tolist(), model.predict_proba(features.tail(1))[0].tolist()))
            validation_accuracy = float(accuracy_score(y_val, predicted)) if len(y_val) else 0.0
            probs = {LABELS[i].lower(): round(float(probabilities.get(i, 0)) * 100, 2) for i in range(3)}
        direction = max(probs, key=probs.get).upper()
        if probs["buy"] > 70:
            signal = "BUY"
        elif probs["sell"] > 70:
            signal = "SELL"
        else:
            signal = "HOLD"
        latest = df.iloc[-1]
        expected = self.expected_move(float(latest["atr"]), float(latest["close"]), float(latest["trend_strength"]))
        return {
            "signal": signal,
            "model_direction": direction,
            "buy_probability": probs.get("buy", 0),
            "sell_probability": probs.get("sell", 0),
            "hold_probability": probs.get("hold", 0),
            "confidence": max(probs.values()),
            "expected_move": expected,
            "expected_window": self.expected_window(float(latest["volatility"])),
            "validation_accuracy": round(validation_accuracy * 100, 2),
            "expires_at": now_utc() + timedelta(hours=24),
        }

    def rule_probabilities(self, latest, imbalance: float, sentiment: float) -> dict:
        score = 50.0
        score += 12 if latest["rsi"] < 30 else -12 if latest["rsi"] > 70 else 0
        score += 10 if latest["macd"] > latest["macd_signal"] else -10
        score += 14 if latest["ema20"] > latest["ema50"] > latest["ema200"] else -14 if latest["ema20"] < latest["ema50"] < latest["ema200"] else 0
        score += max(-8, min(8, imbalance * 16))
        score += max(-6, min(6, sentiment * 6))
        buy = max(5, min(90, score))
        sell = max(5, min(90, 100 - score))
        hold = max(5, 100 - buy - sell)
        total = buy + sell + hold
        return {"buy": round(buy / total * 100, 2), "sell": round(sell / total * 100, 2), "hold": round(hold / total * 100, 2)}

    def rule_probabilities_from_candles(self, candles: list[dict]) -> dict:
        df = calculate_indicators(candles)
        if df.empty:
            return {"up": 0, "down": 0, "sideways": 100}
        probabilities = self.rule_probabilities(df.iloc[-1], 0, 0)
        return {
            "up": probabilities["buy"],
            "down": probabilities["sell"],
            "sideways": probabilities["hold"],
        }

    def expected_move(self, atr: float, close: float, trend_strength: float) -> str:
        pct = 0 if close <= 0 else abs(atr / close * 100) + abs(trend_strength) * 0.25
        pct = max(0.5, min(12.0, pct))
        sign = "+" if trend_strength >= 0 else "-"
        return f"{sign}{pct:.1f}% to {sign}{min(pct * 1.8, 18):.1f}%"

    def expected_window(self, volatility: float) -> str:
        if volatility > 5:
            return "6-12 Hours"
        if volatility > 2.5:
            return "12-24 Hours"
        if volatility > 1:
            return "1-3 Days"
        return "3-7 Days"
