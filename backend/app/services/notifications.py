import httpx
from app.core.config import get_settings


class TelegramNotifier:
    async def send_signal(self, signal: dict) -> None:
        settings = get_settings()
        if not settings.telegram_bot_token or not settings.telegram_chat_id or signal["signal"] == "HOLD":
            return
        text = (
            f"{signal['signal']} SIGNAL\n\n"
            f"{signal['symbol']}\n"
            f"Confidence: {signal['confidence']}%\n"
            f"Expected Move: {signal['expected_move']}\n"
            f"Expected Window: {signal['expected_window']}"
        )
        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(url, json={"chat_id": settings.telegram_chat_id, "text": text})
