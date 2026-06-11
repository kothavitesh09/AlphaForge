class ExchangeConnector:
    def __init__(self, exchange: str):
        self.exchange = exchange

    async def place_order(self, _: dict) -> dict:
        return {"accepted": False, "reason": "Auto trading is disabled"}


class RiskManager:
    def validate(self, settings: dict, order: dict) -> dict:
        if not settings.get("auto_trading_enabled"):
            return {"allowed": False, "reason": "Auto trading feature flag is disabled"}
        if float(order.get("risk_percent", 100)) > 1:
            return {"allowed": False, "reason": "Risk exceeds configured maximum"}
        return {"allowed": True, "reason": "Risk accepted"}


class OrderManager:
    async def submit(self, settings: dict, order: dict) -> dict:
        decision = RiskManager().validate(settings, order)
        if not decision["allowed"]:
            return decision
        return await ExchangeConnector(order["exchange"]).place_order(order)
