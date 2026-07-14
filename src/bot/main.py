import asyncio
import logging
import os

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand, BotCommandScopeChat

from src.bot.config import ADMIN_IDS
from src.bot.db import init_db
from src.bot.handlers import router
from src.bot.notifications.scheduler import notification_loop
from src.bot.notifications.middleware import ActivityMiddleware
from src.bot.retry import RetryRequestMiddleware

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# Меню админа — всплывает при вводе "/" только у пользователей из ADMIN_IDS.
_ADMIN_COMMANDS = [
    BotCommand(command="help", description="Список команд администратора"),
    BotCommand(command="stats", description="Обзор: пользователи, активность, выручка"),
    BotCommand(command="revenue", description="Выручка по периодам и продуктам"),
    BotCommand(command="funnelstats", description="Воронка конверсии и стадии"),
    BotCommand(command="pushstats", description="Эффективность пушей"),
    BotCommand(command="refstats", description="Реферальная статистика"),
    BotCommand(command="funnel", description="Карточка воронки пользователя [id]"),
    BotCommand(command="profile", description="Профиль пользователя <id>"),
    BotCommand(command="photo", description="Фото пользователя <id>"),
    BotCommand(command="reflink", description="Ваша реферальная ссылка"),
]


async def setup_admin_menu(bot: Bot) -> None:
    """Ставит админское меню команд каждому админу в его личном чате."""
    for admin_id in ADMIN_IDS:
        try:
            await bot.set_my_commands(
                _ADMIN_COMMANDS,
                scope=BotCommandScopeChat(chat_id=admin_id),
            )
        except Exception:
            logger.warning("Не удалось установить меню админу %s", admin_id, exc_info=True)


async def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        logger.error("BOT_TOKEN не задан в .env")
        return

    await init_db()

    bot = Bot(token=token)
    bot.session.middleware(RetryRequestMiddleware())
    dp = Dispatcher()
    dp.include_router(router)
    dp.message.outer_middleware(ActivityMiddleware())
    dp.callback_query.outer_middleware(ActivityMiddleware())

    await setup_admin_menu(bot)

    asyncio.create_task(notification_loop(bot))

    logger.info("Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())