"""Система пушей (воронка конверсии).

Импорт этого пакета регистрирует модели UserEvent/NotificationLog в
Base.metadata (нужно до init_db).
"""
from src.bot.notifications.models import UserEvent, NotificationLog  # noqa: F401
from src.bot.notifications.events import (  # noqa: F401
    log_event,
    log_event_once,
    mark_purchase_completed,
    reset_notification_state,
    REGISTRATION_STARTED,
    PROFILE_COMPLETED,
    ENTERED_MENU,
    COUPLE_PARTNER_STARTED,
    COUPLE_PARTNER_COMPLETED,
    DEMO_SHOWN,
    PAYMENT_INITIATED,
    PURCHASE_COMPLETED,
    PROFILE_RESET,
)

__all__ = [
    "UserEvent",
    "NotificationLog",
    "log_event",
    "log_event_once",
    "mark_purchase_completed",
    "reset_notification_state",
    "notification_loop",
    "ActivityMiddleware",
]

# Импортируем в конце, чтобы избежать циклов (scheduler/middleware тянут events)
from src.bot.notifications.scheduler import notification_loop  # noqa: F401,E402
from src.bot.notifications.middleware import ActivityMiddleware  # noqa: F401,E402
