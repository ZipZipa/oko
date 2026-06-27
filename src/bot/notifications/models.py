"""Реэкспорт моделей уведомлений.

Сами модели определены в src.bot.db.models (общий Base для корректного
Base.metadata.create_all).
"""
from src.bot.db.models import UserEvent, NotificationLog

__all__ = ["UserEvent", "NotificationLog"]
