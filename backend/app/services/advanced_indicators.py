import numpy as np
import pandas as pd
from datetime import datetime, timezone
from app.services.indicators import calculate_indicators


class AdvancedIndicatorEngine:
    def calculate(self, candles: list[dict]) -> dict:
        df = calculate_indicators(candles)
        if df.empty:
            return {}
        df["sma20"] = df["close"].rolling(20).mean().fillna(df["close"])
        df["sma50"] = df["close"].rolling(50).mean().fillna(df["close"])
        df["obv"] = (np.sign(df["close"].diff()).fillna(0) * df["volume"]).cumsum()
        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        cumulative_volume = df["volume"].cumsum().replace(0, np.nan)
        df["vwap"] = (typical_price * df["volume"]).cumsum() / cumulative_volume
        low_rsi = df["rsi"].rolling(14).min()
        high_rsi = df["rsi"].rolling(14).max()
        df["stoch_rsi"] = ((df["rsi"] - low_rsi) / (high_rsi - low_rsi).replace(0, np.nan) * 100).fillna(50)
        df["adx"] = self.adx(df)
        latest = df.iloc[-1]
        supports, resistances = self.support_resistance(df)
        return {
            "timestamp": str(latest.get("timestamp", "")),
            "rsi": round(float(latest["rsi"]), 2),
            "macd": round(float(latest["macd"]), 8),
            "macd_signal": round(float(latest["macd_signal"]), 8),
            "ema20": round(float(latest["ema20"]), 8),
            "ema50": round(float(latest["ema50"]), 8),
            "ema200": round(float(latest["ema200"]), 8),
            "sma20": round(float(latest["sma20"]), 8),
            "sma50": round(float(latest["sma50"]), 8),
            "bollinger_upper": round(float(latest["bb_upper"]), 8),
            "bollinger_mid": round(float(latest["bb_mid"]), 8),
            "bollinger_lower": round(float(latest["bb_lower"]), 8),
            "atr": round(float(latest["atr"]), 8),
            "adx": round(float(latest["adx"]), 2),
            "obv": round(float(latest["obv"]), 2),
            "vwap": round(float(latest["vwap"]), 8),
            "stochastic_rsi": round(float(latest["stoch_rsi"]), 2),
            "volume_spike": bool(float(latest["volume_ratio"]) >= 1.8),
            "volume_ratio": round(float(latest["volume_ratio"]), 2),
            "support_levels": supports,
            "resistance_levels": resistances,
        }

    def adx(self, df: pd.DataFrame) -> pd.Series:
        up_move = df["high"].diff()
        down_move = -df["low"].diff()
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)
        atr = df["atr"].replace(0, np.nan)
        plus_di = 100 * pd.Series(plus_dm, index=df.index).rolling(14).mean() / atr
        minus_di = 100 * pd.Series(minus_dm, index=df.index).rolling(14).mean() / atr
        dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)) * 100
        return dx.rolling(14).mean().fillna(20)

    def support_resistance(self, df: pd.DataFrame) -> tuple[list[float], list[float]]:
        recent = df.tail(80)
        supports = recent["low"].rolling(5, center=True).min().dropna().nsmallest(3).tolist()
        resistances = recent["high"].rolling(5, center=True).max().dropna().nlargest(3).tolist()
        return [round(float(x), 8) for x in supports], [round(float(x), 8) for x in resistances]


async def persist_latest_indicators(db, symbol: str, interval: str, candles: list[dict]) -> dict:
    result = AdvancedIndicatorEngine().calculate(candles)
    if not result:
        return {}
    timestamp = result.get("timestamp") or candles[-1].get("timestamp")
    document = {
        "symbol": symbol.upper(),
        "interval": interval,
        "timeframe": interval,
        "timestamp": timestamp,
        "source": str(candles[-1].get("source") or "coindcx"),
        **result,
        "updated_at": datetime.now(timezone.utc),
    }
    await db.indicator_data.update_one(
        {"symbol": document["symbol"], "interval": interval, "timestamp": timestamp},
        {"$set": document, "$setOnInsert": {"created_at": datetime.now(timezone.utc)}},
        upsert=True,
    )
    return result
