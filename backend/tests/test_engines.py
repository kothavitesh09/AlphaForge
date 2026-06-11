from app.services.advanced_indicators import AdvancedIndicatorEngine
from app.services.decision_engine import InstitutionalDecisionEngine
from app.services.market_trend import MarketTrendEngine


def candles(count=80):
    rows = []
    price = 100.0
    for index in range(count):
        price += 0.5
        rows.append({"timestamp": f"2026-01-01T00:{index:02d}:00Z", "open": price - 0.2, "high": price + 1, "low": price - 1, "close": price, "volume": 1000 + index})
    return rows


def decision_payload():
    return {
        "market": {"coin": "BTC", "pair": "BTC_INR", "current_price": 100, "exchange_volume_sufficient": True},
        "technical": {"trend_direction": "UP", "trend_strength": 88, "trend_confirmation": True, "strong_trend_confirmation": True, "setup_type": "TREND", "rsi": 52, "macd_state": "BULLISH", "ema_state": "BULLISH"},
        "volume": {"volume_confirmation": True, "buy_sell_pressure": "BUY", "order_book_imbalance": 0.12, "smart_money_flow": "POSITIVE"},
        "sentiment": {"fear_greed_index": "NEUTRAL", "news_sentiment": 0.2, "reddit_sentiment": 0.1, "twitter_x_sentiment": 0.1, "community_momentum": "POSITIVE"},
        "onchain": {"exchange_flow": "OUTFLOW", "active_addresses": "RISING", "large_transactions": "NORMAL", "wallet_accumulation": "POSITIVE", "token_unlock_events": "NONE"},
        "risk": {"volatility_level": "LOW", "liquidity_risk": "LOW", "drawdown_risk": "LOW", "manipulation_risk": "LOW", "maximum_drawdown_percent": 1.5},
        "profitability": {"entry_price": 100, "stop_loss": 98.5, "take_profit_1": 103, "take_profit_2": 104.5, "take_profit_3": 106, "risk_reward": 2.0, "gross_profit_percent": 3, "total_fees_percent": 0.8, "tds_percent": 0, "slippage_percent": 0.2, "net_profit_percent": 2.2, "stop_distance_percent": 1.5},
        "scores": {"technical_score": 90, "volume_score": 88, "sentiment_score": 82, "onchain_score": 80, "risk_score": 90, "profitability_score": 86},
    }


def test_advanced_indicators():
    result = AdvancedIndicatorEngine().calculate(candles())
    assert "rsi" in result
    assert "vwap" in result
    assert result["support_levels"]


def test_market_trend():
    result = MarketTrendEngine().analyze(candles())
    assert result["trend"] in {"Bullish", "Bearish", "Neutral"}
    assert 0 <= result["trend_score"] <= 100


def test_institutional_decision_trade():
    decision = InstitutionalDecisionEngine().decide(decision_payload())
    assert decision["status"] == "TRADE"
    assert decision["signal_type"] == "BUY"


def test_institutional_decision_no_trade():
    payload = decision_payload()
    payload["scores"]["technical_score"] = 10
    decision = InstitutionalDecisionEngine().decide(payload)
    assert decision["status"] == "NO_TRADE"
