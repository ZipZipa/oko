"""Session middleware: ретраи вызовов Bot API при сетевых сбоях.

Секундный обрыв сети между сервером и api.telegram.org не должен терять
сообщения (особенно отчёты, которые генерировались минуты). Middleware
повторяет упавший запрос с растущей паузой.

Нюанс: при таймауте запрос мог на самом деле дойти до Telegram — тогда
ретрай отправит сообщение второй раз. Для этого бота дубль лучше недоставки.
"""
import asyncio
import logging

from aiogram import Bot
from aiogram.client.session.middlewares.base import (
    BaseRequestMiddleware,
    NextRequestMiddlewareType,
)
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import GetUpdates, TelegramMethod
from aiogram.methods.base import Response, TelegramType

log = logging.getLogger(__name__)

_RETRY_DELAYS = (1, 3, 9)


class RetryRequestMiddleware(BaseRequestMiddleware):
    """Повторяет запрос при TelegramNetworkError (таймаут, обрыв соединения).

    getUpdates не ретраим: polling-цикл aiogram сам переподключается,
    а пауза здесь только задержала бы получение апдейтов.
    """

    async def __call__(
        self,
        make_request: NextRequestMiddlewareType[TelegramType],
        bot: Bot,
        method: TelegramMethod[TelegramType],
    ) -> Response[TelegramType]:
        if isinstance(method, GetUpdates):
            return await make_request(bot, method)

        for attempt, delay in enumerate(_RETRY_DELAYS, start=1):
            try:
                return await make_request(bot, method)
            except TelegramNetworkError as e:
                log.warning(
                    "Bot API %s: сетевая ошибка (%s) — ретрай %d/%d через %dс",
                    type(method).__name__, e, attempt, len(_RETRY_DELAYS), delay,
                )
                await asyncio.sleep(delay)

        # Последняя попытка — без перехвата, чтобы ошибка ушла вызывающему коду
        return await make_request(bot, method)
