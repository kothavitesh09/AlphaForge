import numpy as np
import pandas as pd


def calculate_indicators(candles: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(candles)
    if df.empty:
        return df
    for column in ["open", "high", "low", "close", "volume"]:
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0.0)
    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean().replace(0, np.nan)
    df["rsi"] = (100 - (100 / (1 + gain / loss))).fillna(50)
    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
    df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    mid = df["close"].rolling(20).mean()
    std = df["close"].rolling(20).std().fillna(0)
    df["bb_mid"] = mid.fillna(df["close"])
    df["bb_upper"] = df["bb_mid"] + 2 * std
    df["bb_lower"] = df["bb_mid"] - 2 * std
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    df["atr"] = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1).rolling(14).mean().fillna(0)
    df["volume_ratio"] = (df["volume"] / df["volume"].rolling(20).mean().replace(0, np.nan)).fillna(1)
    df["volatility"] = df["close"].pct_change().rolling(24).std().fillna(0) * 100
    df["trend_strength"] = ((df["ema20"] - df["ema50"]) / df["close"].replace(0, np.nan) * 100).fillna(0)
    return df


def order_book_imbalance(order_book: dict) -> float:
    def side_total(rows: list) -> float:
        total = 0.0
        for row in rows[:20]:
            price = float(row[0] if isinstance(row, list) else row.get("price", row.get("0", 0)))
            qty = float(row[1] if isinstance(row, list) else row.get("quantity", row.get("amount", row.get("1", 0))))
            total += price * qty
        return total
    bids = side_total(order_book.get("bids", []))
    asks = side_total(order_book.get("asks", []))
    return 0 if bids + asks == 0 else (bids - asks) / (bids + asks)
