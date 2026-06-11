from datetime import datetime, timezone
from fastapi import HTTPException
from app.repositories.base import MongoRepository, now_utc
from app.services.market_data import KoinBXClient


STARTING_BALANCE = 100000.0


class PaperTradingService:
    def __init__(self, db):
        self.db = db
        self.trades = MongoRepository(db, "paper_trades")
        self.portfolios = MongoRepository(db, "portfolios")
        self.market = KoinBXClient()

    async def portfolio(self, user_id: str) -> dict:
        await self.auto_close_positions(user_id)
        portfolio = await self._portfolio(user_id)
        positions = portfolio.get("positions", {})
        enriched = {}
        cash = float(portfolio.get("cash_balance", STARTING_BALANCE))
        equity = cash
        unrealized = 0.0
        for position_id, position in positions.items():
            price = await self._price(position["symbol"])
            quantity = float(position["quantity"])
            value = quantity * price
            cost = quantity * float(position["entry_price"])
            pnl = value - cost if position["side"] == "BUY" else cost - value
            equity += value
            unrealized += pnl
            enriched[position_id] = {
                **position,
                "current_price": price,
                "market_value": round(value, 2),
                "unrealized_pnl": round(pnl, 2),
                "duration": self._duration(position.get("opened_at")),
            }
        trades = await self.trades.find_many({"user_id": user_id}, limit=5000, sort=[("created_at", -1)])
        closed = [trade for trade in trades if trade.get("side") == "CLOSE"]
        wins = [trade for trade in closed if float(trade.get("pnl", 0)) > 0]
        realized = sum(float(trade.get("pnl", 0)) for trade in closed)
        return {
            **portfolio,
            "balance": round(equity, 2),
            "portfolio_value": round(equity, 2),
            "available_cash": round(cash, 2),
            "cash_balance": round(cash, 2),
            "equity": round(equity, 2),
            "positions": enriched,
            "open_positions": len(enriched),
            "closed_positions": len(closed),
            "unrealized_pnl": round(unrealized, 2),
            "realized_pnl": round(realized, 2),
            "win_rate": round(len(wins) / len(closed) * 100, 2) if closed else 0,
            "trades": trades[:100],
        }

    async def buy(self, user_id: str, symbol: str, quantity: float) -> dict:
        price = await self._price(symbol)
        return await self.open_position(user_id, symbol, "BUY", quantity, price)

    async def sell(self, user_id: str, symbol: str, quantity: float) -> dict:
        price = await self._price(symbol)
        return await self.close_quantity(user_id, symbol, quantity, price, "manual_sell")

    async def execute_signal(self, user_id: str, signal_id: str, quantity: float | None = None, risk_fraction: float = 0.1) -> dict:
        signal = await MongoRepository(self.db, "signals").find_one({"id": signal_id})
        if not signal:
            raise HTTPException(status_code=404, detail="Signal not found")
        action = signal.get("action") or signal.get("signal")
        if action not in {"BUY", "SELL"}:
            raise HTTPException(status_code=400, detail="Only BUY or SELL signals can be executed")
        entry = float(signal.get("entry") or signal.get("decision", {}).get("entry_price") or 0)
        target = float(signal.get("target") or signal.get("decision", {}).get("take_profit_1") or 0)
        stop = float(signal.get("stop_loss") or signal.get("decision", {}).get("stop_loss") or 0)
        if entry <= 0 or target <= 0 or stop <= 0:
            raise HTTPException(status_code=400, detail="Signal does not include executable prices")
        portfolio = await self._portfolio(user_id)
        cash = float(portfolio.get("cash_balance", STARTING_BALANCE))
        notional = max(0, cash * max(0.01, min(risk_fraction, 1)))
        position_size = quantity or (notional / entry)
        return await self.open_position(user_id, signal["symbol"], action, position_size, entry, target, stop, signal_id)

    async def open_position(self, user_id: str, symbol: str, side: str, quantity: float, entry_price: float, target: float | None = None, stop_loss: float | None = None, signal_id: str | None = None) -> dict:
        if quantity <= 0:
            raise HTTPException(status_code=400, detail="Quantity must be positive")
        portfolio = await self._portfolio(user_id)
        cost = entry_price * quantity
        if float(portfolio["cash_balance"]) < cost:
            raise HTTPException(status_code=400, detail="Insufficient virtual balance")
        position_id = f"{symbol.upper()}-{int(datetime.now(timezone.utc).timestamp() * 1000)}"
        positions = portfolio.get("positions", {})
        positions[position_id] = {
            "id": position_id,
            "signal_id": signal_id,
            "symbol": symbol.upper(),
            "side": side,
            "quantity": quantity,
            "entry_price": entry_price,
            "target": target or (entry_price * 1.02 if side == "BUY" else entry_price * 0.98),
            "stop_loss": stop_loss or (entry_price * 0.99 if side == "BUY" else entry_price * 1.01),
            "position_size": cost,
            "opened_at": now_utc().isoformat(),
        }
        await self.portfolios.upsert_one({"user_id": user_id}, {"cash_balance": float(portfolio["cash_balance"]) - cost, "positions": positions})
        await self.trades.insert({"user_id": user_id, "side": "OPEN", "symbol": symbol.upper(), "action": side, "quantity": quantity, "price": entry_price, "notional": cost, "signal_id": signal_id, "position_id": position_id, "created_at": now_utc()})
        return await self.portfolio(user_id)

    async def close_quantity(self, user_id: str, symbol: str, quantity: float, price: float, reason: str) -> dict:
        portfolio = await self._portfolio(user_id)
        positions = portfolio.get("positions", {})
        for position_id, position in list(positions.items()):
            if position["symbol"] != symbol.upper():
                continue
            close_qty = min(quantity, float(position["quantity"]))
            return await self.close_position(user_id, position_id, price, reason, close_qty)
        raise HTTPException(status_code=400, detail="No open position for symbol")

    async def close_position(self, user_id: str, position_id: str, price: float, reason: str, quantity: float | None = None) -> dict:
        portfolio = await self._portfolio(user_id)
        positions = portfolio.get("positions", {})
        position = positions.get(position_id)
        if not position:
            raise HTTPException(status_code=404, detail="Position not found")
        close_qty = quantity or float(position["quantity"])
        entry = float(position["entry_price"])
        pnl = (price - entry) * close_qty if position["side"] == "BUY" else (entry - price) * close_qty
        proceeds = price * close_qty
        remaining = float(position["quantity"]) - close_qty
        if remaining <= 1e-10:
            positions.pop(position_id, None)
        else:
            position["quantity"] = remaining
            positions[position_id] = position
        await self.portfolios.upsert_one({"user_id": user_id}, {"cash_balance": float(portfolio["cash_balance"]) + proceeds, "positions": positions})
        await self.trades.insert({"user_id": user_id, "side": "CLOSE", "symbol": position["symbol"], "action": position["side"], "quantity": close_qty, "price": price, "notional": proceeds, "pnl": round(pnl, 2), "reason": reason, "position_id": position_id, "signal_id": position.get("signal_id"), "created_at": now_utc()})
        return await self.portfolio(user_id)

    async def auto_close_positions(self, user_id: str) -> None:
        portfolio = await self._portfolio(user_id, create=False)
        if not portfolio:
            return
        for position_id, position in list(portfolio.get("positions", {}).items()):
            price = await self._price(position["symbol"])
            side = position["side"]
            target = float(position["target"])
            stop = float(position["stop_loss"])
            if side == "BUY" and price >= target:
                await self.close_position(user_id, position_id, target, "target_hit")
            elif side == "BUY" and price <= stop:
                await self.close_position(user_id, position_id, stop, "stop_hit")
            elif side == "SELL" and price <= target:
                await self.close_position(user_id, position_id, target, "target_hit")
            elif side == "SELL" and price >= stop:
                await self.close_position(user_id, position_id, stop, "stop_hit")

    async def _portfolio(self, user_id: str, create: bool = True) -> dict | None:
        portfolio = await self.portfolios.find_one({"user_id": user_id})
        if not portfolio and create:
            portfolio = await self.portfolios.insert({"user_id": user_id, "cash_balance": STARTING_BALANCE, "positions": {}})
        return portfolio

    async def _price(self, symbol: str) -> float:
        latest = await self.db.market_data.find_one({"symbol": symbol.upper()}, sort=[("timestamp", -1)])
        if latest:
            return float(latest.get("close") or 0)
        ticker = await self.market.ticker(symbol)
        return float(ticker["last"])

    def _duration(self, opened_at: str | None) -> str:
        if not opened_at:
            return "0m"
        opened = datetime.fromisoformat(str(opened_at).replace("Z", "+00:00"))
        minutes = int((now_utc() - opened).total_seconds() // 60)
        if minutes < 60:
            return f"{minutes}m"
        return f"{minutes // 60}h {minutes % 60}m"
