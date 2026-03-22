from telegram import Bot
from config.settings import settings

_bot = Bot(token=settings.telegram_bot_token)

async def send_messages(messages: list[str]):
    for msg in messages:
        await _bot.send_message(
            chat_id=settings.telegram_chat_id,
            text=msg,
            parse_mode="Markdown",
        )