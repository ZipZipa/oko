"""Фиксация событий пользователя для системы пушей.

События пишутся в append-only таблицу user_events. Планировщик
(scheduler.py) читает их и решает, какие пуши отправить.
"""
import json
import logging

from datetime import datetime, timezone
from sqlalchemy import select, delete

from src.bot.db import async_session
from src.bot.notifications.models import UserEvent, NotificationLog

log = logging.getLogger(__name__)

# Событие 1
# Зашёл → ничего не начал
# Пуш 1 — через 15 минут
# Твой персональный анализ ещё не начат.
# Пуш 2 — через 24 часа
# Ответы о тебе всё ещё ждут тебя в ОКО.

# Событие 2
# Начал анализ → бросил на заполнении данных
# (дата, фото лица, ладони)
# Пуш 1 — через 30 минут
# Ты почти начал анализ. Остался последний шаг.
# Пуш 2 — через 12 часов
# Дополни данные и получи свой персональный разбор.

# Событие 3
# Начал совместимость → не ввёл партнёра
# Пуш 1 — через 30 минут
# Для анализа пары не хватает данных второго человека.
# Пуш 2 — через 24 часа
# Добавь данные партнёра и узнай, что происходит между вами на самом деле.

# Событие 4
# Получил демо → не купил
# Пуш 1 — через 20 минут
# Ты увидел только часть своего анализа.
# Пуш 2 — через 12 часов
# Самые важные выводы остались закрыты.
# Пуш 3 — через 48 часов
# Полный разбор всё ещё доступен.

# Событие 5
# Нажал оплатить → не оплатил
# Пуш 1 — через 15 минут
# Оплата не завершена. Твой анализ уже готов.
# Пуш 2 — через 3 часа
# Остался один шаг до полного доступа.
# Пуш 3 — через 24 часа
# Заверши оплату и открой свой разбор.

# Событие 6
# Купил один продукт → не купил остальные
# Через 24 часа.
# Купил Личность:
# Теперь узнай, как твои особенности влияют на деньги и отношения.
# Купил Деньги:
# Теперь узнай, какие отношения усиливают или ослабляют твой путь.
# Купил Совместимость:
# Теперь узнай, почему именно такие люди появляются в твоей жизни.

# Событие 7
# Купил базовый или расширенный → не купил премиум
# Через 2 часа
# Ты открыл только часть своего анализа.
# Через 24 часа
# Самые глубокие выводы доступны в Премиум.

# Событие 8
# Был раньше в боте → долго не заходил
# 7 дней:
# Твои разборы всё ещё ждут тебя.
# 30 дней:
# Возможно, сейчас именно то время, чтобы посмотреть на свою жизнь иначе.

# ── Типы событий ──────────────────────────────────────────────────────────────
REGISTRATION_STARTED = "registration_started"          # E2: начал регистрацию
PROFILE_COMPLETED = "profile_completed"                # E2 отмена / E1 база
ENTERED_MENU = "entered_menu"                          # E1: зашёл в главное меню
COUPLE_PARTNER_STARTED = "couple_partner_started"      # E3: начал совместимость
COUPLE_PARTNER_COMPLETED = "couple_partner_completed"  # E3 отмена
DEMO_SHOWN = "demo_shown"                              # E4: получил демо
PAYMENT_INITIATED = "payment_initiated"                # E5: нажал оплатить
PURCHASE_COMPLETED = "purchase_completed"              # E4 отмена / E6 / E7
PROFILE_RESET = "profile_reset"                        # сброс данных


async def log_event(
    telegram_id: int,
    event_type: str,
    report_type: str | None = None,
    plan: str | None = None,
    payment_id: str | None = None,
    payload: dict | None = None,
) -> None:
    """Записать событие (всегда добавляет новую строку)."""
    try:
        async with async_session() as session:
            session.add(UserEvent(
                telegram_id=telegram_id,
                event_type=event_type,
                report_type=report_type,
                plan=plan,
                payment_id=payment_id,
                created_at=datetime.now(timezone.utc),
                payload_json=json.dumps(payload, ensure_ascii=False) if payload else None,
            ))
            await session.commit()
    except Exception:
        log.error("log_event failed: %s tg=%s", event_type, telegram_id, exc_info=True)


async def log_event_once(
    telegram_id: int,
    event_type: str,
    report_type: str | None = None,
    plan: str | None = None,
    payment_id: str | None = None,
    payload: dict | None = None,
) -> bool:
    """Записать событие, только если такого ещё нет для пользователя.

    Уникальность по (telegram_id, event_type, report_type, payment_id).
    После reset_notification_state старые события удаляются —
    поэтому log_event_once снова сработает после сброса.
    """
    try:
        async with async_session() as session:
            stmt = select(UserEvent.id).where(
                UserEvent.telegram_id == telegram_id,
                UserEvent.event_type == event_type,
            )
            if report_type is not None:
                stmt = stmt.where(UserEvent.report_type == report_type)
            if payment_id is not None:
                stmt = stmt.where(UserEvent.payment_id == payment_id)
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if existing is not None:
                return False
            session.add(UserEvent(
                telegram_id=telegram_id,
                event_type=event_type,
                report_type=report_type,
                plan=plan,
                payment_id=payment_id,
                created_at=datetime.now(timezone.utc),
                payload_json=json.dumps(payload, ensure_ascii=False) if payload else None,
            ))
            await session.commit()
            return True
    except Exception:
        log.error("log_event_once failed: %s tg=%s", event_type, telegram_id, exc_info=True)
        return False


async def mark_purchase_completed(
    telegram_id: int,
    report_type: str,
    plan: str,
    payment_id: str,
) -> None:
    """Зафиксировать успешную покупку (идемпотентно по payment_id)."""
    await log_event_once(
        telegram_id, PURCHASE_COMPLETED,
        report_type=report_type, plan=plan, payment_id=payment_id,
    )


async def reset_notification_state(telegram_id: int) -> None:
    """Полная очистка состояния пушей для пользователя (при сбросе данных).

    Удаляет все user_events и notification_log, затем логирует свежий
    registration_started — это перезапускает воронку E2.
    """
    try:
        async with async_session() as session:
            await session.execute(
                delete(UserEvent).where(UserEvent.telegram_id == telegram_id)
            )
            await session.execute(
                delete(NotificationLog).where(NotificationLog.telegram_id == telegram_id)
            )
            await session.commit()
    except Exception:
        log.error("reset_notification_state failed tg=%s", telegram_id, exc_info=True)
    await log_event(telegram_id, REGISTRATION_STARTED)
