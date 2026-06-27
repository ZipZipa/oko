"""Middleware обновления last_activity_at на каждое взаимодействие.

Также очищает e8:* из notification_log, чтобы пуш «давно не заходил»
мог сработать заново в следующем цикле неактивности, и снимает флаг
is_blocked, если пользователь снова написал (разблокировал бота).
"""
import logging

from datetime import datetime, timezone
from sqlalchemy import select, delete

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject

from src.bot.db import async_session, User
from src.bot.notifications.models import NotificationLog

log = logging.getLogger(__name__)

_E8_KEYS = ("e8:1", "e8:2")


class ActivityMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        tg_id = None
        if isinstance(event, (Message, CallbackQuery)) and event.from_user:
            tg_id = event.from_user.id

        if tg_id is not None:
            try:
                async with async_session() as session:
                    result = await session.execute(
                        select(User).where(User.telegram_id == tg_id)
                    )
                    user = result.scalar_one_or_none()
                    if user is not None:
                        user.last_activity_at = datetime.now(timezone.utc)
                        if user.is_blocked:
                            user.is_blocked = False
                        await session.execute(
                            delete(NotificationLog).where(
                                NotificationLog.telegram_id == tg_id,
                                NotificationLog.event_key.in_(_E8_KEYS),
                            )
                        )
                        await session.commit()
            except Exception:
                log.error("ActivityMiddleware update failed tg=%s", tg_id, exc_info=True)

        return await handler(event, data)
