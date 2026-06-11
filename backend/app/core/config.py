from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


SUPPORTED_SYMBOLS = (
    "BTC_INR",
    "ETH_INR",
    "SOL_INR",
    "BNB_INR",
    "XRP_INR",
    "DOGE_INR",
    "TRX_INR",
    "DOT_INR",
    "AVAX_INR",
    "ATOM_INR",
    "BDX_INR",
    "MATIC_INR",
    "LINK_INR",
    "ADA_INR",
)

SUPPORTED_INTERVALS = ("1m", "5m", "15m", "1h", "4h", "1d")


class Settings(BaseSettings):
    mongodb_uri: str = Field(..., alias="MONGODB_URI")
    mongodb_database: str = Field("alphaforge", alias="MONGODB_DATABASE")
    jwt_secret: str = Field(..., alias="JWT_SECRET")
    koinbx_base_url: str = Field("https://api.koinbx.com", alias="KOINBX_BASE_URL")
    market_data_symbols: str = Field(",".join(SUPPORTED_SYMBOLS), alias="MARKET_DATA_SYMBOLS")
    market_data_intervals: str = Field(",".join(SUPPORTED_INTERVALS), alias="MARKET_DATA_INTERVALS")
    telegram_bot_token: str | None = Field(None, alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str | None = Field(None, alias="TELEGRAM_CHAT_ID")
    allowed_origins: str = Field("http://localhost:3000", alias="ALLOWED_ORIGINS")
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60 * 24
    app_name: str = "AlphaForge"

    model_config = SettingsConfigDict(env_file=(".env", "backend/.env"), populate_by_name=True, extra="ignore")

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @property
    def collector_symbols(self) -> list[str]:
        configured = [symbol.strip().upper() for symbol in self.market_data_symbols.split(",") if symbol.strip()]
        return [symbol for symbol in configured if symbol in SUPPORTED_SYMBOLS] or list(SUPPORTED_SYMBOLS)

    @property
    def collector_intervals(self) -> list[str]:
        configured = [interval.strip() for interval in self.market_data_intervals.split(",") if interval.strip()]
        return [interval for interval in configured if interval in SUPPORTED_INTERVALS] or list(SUPPORTED_INTERVALS)


@lru_cache
def get_settings() -> Settings:
    return Settings()
