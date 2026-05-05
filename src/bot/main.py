import asyncio
import logging
import os

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher

from src.bot.db import init_db
from src.bot.handlers import router

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        logger.error("BOT_TOKEN не задан в .env")
        return

    await init_db()

    bot = Bot(token=token)
    dp = Dispatcher()
    dp.include_router(router)

    logger.info("Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())