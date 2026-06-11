import math
from app.repositories.base import MongoRepository, now_utc


class BacktestingService:
    def __init__(self, db):
        self.results = MongoRepository(db, "backtest_results")

    async def run(self, symbol: str, candles: list[dict], signals: list[dict]) -> dict:
        closed = []
        ordered = sorted(candles, key=lambda item: item["timestamp"])
        for signal in signals:
            decision = signal.get("decision") or {}
            if decision.get("status") != "TRADE":
                continue
            entry = float(decision["entry_price"])
            target = float(decision["take_profit_1"])
            stop = float(decision["stop_loss"])
            side = decision["signal_type"]
            future = [c for c in ordered if str(c["timestamp"]) > str(signal.get("created_at", ""))]
            exit_price = entry
            outcome = "OPEN"
            for candle in future:
                high = float(candle["high"])
                low = float(candle["low"])
                if side == "BUY" and high >= target:
                    exit_price, outcome = target, "TARGET_HIT"
                    break
                if side == "BUY" and low <= stop:
                    exit_price, outcome = stop, "STOP_LOSS_HIT"
                    break
                if side == "SELL" and low <= target:
                    exit_price, outcome = target, "TARGET_HIT"
                    break
                if side == "SELL" and high >= stop:
                    exit_price, outcome = stop, "STOP_LOSS_HIT"
                    break
            if outcome != "OPEN":
                pnl = (exit_price - entry) / entry * 100 if side == "BUY" else (entry - exit_price) / entry * 100
                closed.append({"entry": entry, "exit": exit_price, "outcome": outcome, "return_percent": pnl})
        returns = [trade["return_percent"] for trade in closed]
        wins = [value for value in returns if value > 0]
        losses = [abs(value) for value in returns if value < 0]
        result = {
            "symbol": symbol.upper(),
            "trades": len(closed),
            "win_rate": round(len(wins) / len(closed) * 100, 2) if closed else 0,
            "average_return": round(sum(returns) / len(returns), 2) if returns else 0,
            "max_drawdown": round(min(returns), 2) if returns else 0,
            "profit_factor": round(sum(wins) / sum(losses), 2) if losses else round(sum(wins), 2),
            "sharpe_ratio": self.sharpe(returns),
            "closed_trades": closed[-50:],
            "created_at": now_utc(),
        }
        return await self.results.insert(result)

    def sharpe(self, returns: list[float]) -> float:
        if len(returns) < 2:
            return 0
        avg = sum(returns) / len(returns)
        variance = sum((value - avg) ** 2 for value in returns) / (len(returns) - 1)
        stdev = math.sqrt(variance)
        return round(avg / stdev, 2) if stdev else 0
