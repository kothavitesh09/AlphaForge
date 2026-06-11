from app.repositories.base import MongoRepository


DEFAULT_SETTINGS = {
    "exchange_selection": "CoinDCX",
    "refresh_interval": 30,
    "risk_profile": "Balanced",
    "theme": "Dark",
    "api_configuration": {"coindcx_enabled": True, "koinbx_enabled": True},
    "auto_trading_enabled": False,
}


class SettingsService:
    def __init__(self, db):
        self.settings = MongoRepository(db, "settings")

    async def get(self, user_id: str) -> dict:
        saved = await self.settings.find_one({"user_id": user_id})
        return saved or await self.settings.upsert_one({"user_id": user_id}, {"user_id": user_id, **DEFAULT_SETTINGS})

    async def update(self, user_id: str, payload: dict) -> dict:
        allowed = {key: value for key, value in payload.items() if key in DEFAULT_SETTINGS}
        if "auto_trading_enabled" in allowed:
            allowed["auto_trading_enabled"] = False
        return await self.settings.upsert_one({"user_id": user_id}, {"user_id": user_id, **allowed})
