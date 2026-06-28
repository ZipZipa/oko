"""Планировщик пушей.

Фоновая asyncio-таска раз в минуту делает sweep: для каждого события
(E1–E8) находит кандидатов, проверяет условия отмены и отправляет пуши,
логируя их в notification_log (идемпотентность).
"""
import asyncio
import logging

from collections import defaultdict
from datetime import datetime, timezone, timedelta
from html import escape as _html_escape

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.bot.config import BOT_USERNAME
from src.bot.db import async_session, User, Payment
from src.bot.db.models import UserEvent, NotificationLog
from src.bot.messages import MESSAGES
from src.bot.notifications.events import (
    REGISTRATION_STARTED, PROFILE_COMPLETED, ENTERED_MENU,
    COUPLE_PARTNER_STARTED, COUPLE_PARTNER_COMPLETED,
    DEMO_SHOWN, PAYMENT_INITIATED, PURCHASE_COMPLETED,
)
from src.bot.notifications.payments_poller import poll_pending_payments

log = logging.getLogger(__name__)

_REPORTS = ("self", "money", "couple")


# ─── Хелперы времени ──────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ─── Клавиатуры ───────────────────────────────────────────────────────────────

def _bot_url() -> str | None:
    if not BOT_USERNAME:
        return None
    return f"https://t.me/{BOT_USERNAME}?start=continue"


def _open_bot_kb() -> InlineKeyboardMarkup | None:
    url = _bot_url()
    if not url:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Перейти в ОКО", url=url),
    ]])


def _payment_kb(confirmation_url: str | None) -> InlineKeyboardMarkup | None:
    rows: list[list[InlineKeyboardButton]] = []
    if confirmation_url:
        rows.append([InlineKeyboardButton(text="Перейти к оплате", url=confirmation_url)])
    url = _bot_url()
    if url:
        rows.append([InlineKeyboardButton(text="Открыть ОКО", url=url)])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


# ─── Отправка / журнал ────────────────────────────────────────────────────────

async def _mark_blocked(telegram_id: int) -> None:
    try:
        async with async_session() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = result.scalar_one_or_none()
            if user and not user.is_blocked:
                user.is_blocked = True
                await session.commit()
    except Exception:
        log.error("_mark_blocked failed tg=%s", telegram_id, exc_info=True)


async def _send_push(
    bot: Bot, telegram_id: int, msg_key: str,
    reply_markup=None, **fmt,
) -> bool:
    text = MESSAGES[msg_key].text
    if fmt:
        text = text.format(**{k: _html_escape(str(v)) for k, v in fmt.items()})
    try:
        await bot.send_message(
            telegram_id, text, parse_mode="HTML", reply_markup=reply_markup,
        )
        return True
    except TelegramForbiddenError:
        await _mark_blocked(telegram_id)
        return False
    except TelegramBadRequest as e:
        msg = str(e).lower()
        if "blocked" in msg or "chat not found" in msg or "user is deactivated" in msg:
            await _mark_blocked(telegram_id)
        else:
            log.error("send_push badrequest %s %s: %s", telegram_id, msg_key, e)
        return False
    except Exception:
        log.error("send_push failed %s %s", telegram_id, msg_key, exc_info=True)
        return False


async def _already_sent(session, telegram_id: int, event_key: str) -> bool:
    result = await session.execute(
        select(NotificationLog.id).where(
            NotificationLog.telegram_id == telegram_id,
            NotificationLog.event_key == event_key,
        )
    )
    return result.scalar_one_or_none() is not None


async def _mark_sent(session, telegram_id: int, event_key: str) -> None:
    session.add(NotificationLog(telegram_id=telegram_id, event_key=event_key))
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()


async def _try_send(
    bot, session, telegram_id, event_key, msg_key,
    reply_markup=None, **fmt,
) -> bool:
    """Отправить пуш, если ещё не отправлен. Возвращает True если отправил."""
    if await _already_sent(session, telegram_id, event_key):
        return False
    if await _send_push(bot, telegram_id, msg_key, reply_markup=reply_markup, **fmt):
        await _mark_sent(session, telegram_id, event_key)
        return True
    return False


# ─── Запросы событий ──────────────────────────────────────────────────────────

async def _fetch_events(session, event_types) -> list[UserEvent]:
    result = await session.execute(
        select(UserEvent).where(UserEvent.event_type.in_(event_types))
        .order_by(UserEvent.created_at.asc())
    )
    return list(result.scalars().all())


def _latest_per_user(events: list[UserEvent]) -> dict[int, UserEvent]:
    """Последнее событие на каждого пользователя."""
    latest: dict[int, UserEvent] = {}
    for ev in events:
        latest[ev.telegram_id] = ev  # events отсортированы по возрастанию
    return latest


# ─── E1: Зашёл → ничего не начал ──────────────────────────────────────────────

async def _check_e1(bot, session):
    """E1. Зашёл в меню → ничего не начал.

    Кандидат: полный профиль + был entered_menu, но НИКОГДА не начинал
    анализ (нет demo_shown / payment_initiated / couple_partner_started /
    purchase_completed). Проверяем «когда-либо», а не «после последнего
    входа»: иначе повторный заход в меню (/start, «← В меню») перезаписывает
    entered_menu свежим временем, демо оказываются «до» него — и E1
    ложно срабатывает для уже конвертированного пользователя.
    """
    now = _now()
    entered = _latest_per_user(await _fetch_events(session, [ENTERED_MENU]))
    if not entered:
        return
    cancels = await _fetch_events(
        session, [DEMO_SHOWN, PAYMENT_INITIATED, COUPLE_PARTNER_STARTED, PURCHASE_COMPLETED]
    )
    converted: set[int] = {ev.telegram_id for ev in cancels}

    # пользователи с полным профилем и не заблокированные
    users_result = await session.execute(
        select(User).where(
            User.is_blocked.is_(False),
            User.name.isnot(None),
            User.face_json.isnot(None),
            User.birth_date.isnot(None),
        )
    )
    for user in users_result.scalars():
        if user.telegram_id in converted:
            continue  # уже начал анализ — E1 неактуален
        em = entered.get(user.telegram_id)
        if not em:
            continue
        em_t = _as_utc(em.created_at)
        age = now - em_t
        if age >= timedelta(minutes=15):
            await _try_send(bot, session, user.telegram_id, "e1:1", "push_e1_1", _open_bot_kb())
        if age >= timedelta(hours=24):
            await _try_send(bot, session, user.telegram_id, "e1:2", "push_e1_2", _open_bot_kb())


# ─── E2: Начал регистрацию → бросил ───────────────────────────────────────────

async def _check_e2(bot, session):
    now = _now()
    started = _latest_per_user(await _fetch_events(session, [REGISTRATION_STARTED]))
    if not started:
        return
    completed = await _fetch_events(session, [PROFILE_COMPLETED])

    for tg_id, ev in started.items():
        ev_t = _as_utc(ev.created_at)
        # отмена: profile_completed после старта
        if any(
            _as_utc(c.created_at) > ev_t and c.telegram_id == tg_id
            for c in completed
        ):
            continue
        age = now - ev_t
        if age >= timedelta(minutes=30):
            await _try_send(bot, session, tg_id, "e2:1", "push_e2_1", _open_bot_kb())
        if age >= timedelta(hours=12):
            await _try_send(bot, session, tg_id, "e2:2", "push_e2_2", _open_bot_kb())


# ─── E3: Начал совместимость → не ввёл партнёра ───────────────────────────────

async def _check_e3(bot, session):
    now = _now()
    started = _latest_per_user(await _fetch_events(session, [COUPLE_PARTNER_STARTED]))
    if not started:
        return
    completed = await _fetch_events(session, [COUPLE_PARTNER_COMPLETED])

    for tg_id, ev in started.items():
        ev_t = _as_utc(ev.created_at)
        if any(
            _as_utc(c.created_at) > ev_t and c.telegram_id == tg_id
            for c in completed
        ):
            continue
        age = now - ev_t
        if age >= timedelta(minutes=30):
            await _try_send(bot, session, tg_id, "e3:1", "push_e3_1", _open_bot_kb())
        if age >= timedelta(hours=24):
            await _try_send(bot, session, tg_id, "e3:2", "push_e3_2", _open_bot_kb())


# ─── E4: Получил демо → не купил ──────────────────────────────────────────────

async def _check_e4(bot, session):
    now = _now()
    demos = await _fetch_events(session, [DEMO_SHOWN])
    if not demos:
        return
    # последние demo_shown на (пользователь, report_type)
    latest: dict[tuple[int, str], UserEvent] = {}
    for ev in demos:
        latest[(ev.telegram_id, ev.report_type)] = ev

    cancels = await _fetch_events(session, [PAYMENT_INITIATED, PURCHASE_COMPLETED])
    cancels_after: dict[tuple[int, str], list[UserEvent]] = defaultdict(list)
    for ev in cancels:
        cancels_after[(ev.telegram_id, ev.report_type)].append(ev)

    for (tg_id, report_type), ev in latest.items():
        ev_t = _as_utc(ev.created_at)
        if any(_as_utc(c.created_at) > ev_t for c in cancels_after.get((tg_id, report_type), [])):
            continue
        age = now - ev_t
        ek = f"e4:{report_type}"
        if age >= timedelta(minutes=20):
            await _try_send(bot, session, tg_id, f"{ek}:1", "push_e4_1", _open_bot_kb())
        if age >= timedelta(hours=12):
            await _try_send(bot, session, tg_id, f"{ek}:2", "push_e4_2", _open_bot_kb())
        if age >= timedelta(hours=48):
            await _try_send(bot, session, tg_id, f"{ek}:3", "push_e4_3", _open_bot_kb())


# ─── E5: Нажал оплатить → не оплатил ──────────────────────────────────────────

async def _check_e5(bot, session):
    now = _now()
    result = await session.execute(
        select(Payment).where(Payment.status == "pending")
    )
    pending = list(result.scalars().all())
    if not pending:
        return
    # последний pending-платёж на пользователя
    latest: dict[int, Payment] = {}
    for p in pending:
        cur = latest.get(p.telegram_id)
        if cur is None or _as_utc(p.created_at) > _as_utc(cur.created_at):
            latest[p.telegram_id] = p

    # статус блокировки
    blocked_ids: set[int] = set()
    if latest:
        users_result = await session.execute(
            select(User.telegram_id).where(
                User.telegram_id.in_(list(latest.keys())),
                User.is_blocked.is_(True),
            )
        )
        blocked_ids = set(users_result.scalars().all())

    for tg_id, payment in latest.items():
        if tg_id in blocked_ids:
            continue
        age = now - _as_utc(payment.created_at)
        ek = f"e5:{payment.yookassa_id}"
        kb = _payment_kb(payment.confirmation_url)
        if age >= timedelta(minutes=15):
            await _try_send(bot, session, tg_id, f"{ek}:1", "push_e5_1", kb)
        if age >= timedelta(hours=3):
            await _try_send(bot, session, tg_id, f"{ek}:2", "push_e5_2", kb)
        if age >= timedelta(hours=24):
            await _try_send(bot, session, tg_id, f"{ek}:3", "push_e5_3", kb)


# ─── E6: Купил один продукт → не купил остальные ──────────────────────────────

async def _check_e6(bot, session):
    now = _now()
    purchases = await _fetch_events(session, [PURCHASE_COMPLETED])
    if not purchases:
        return
    # report_types, купленные пользователем (по событиям)
    bought: dict[int, set[str]] = defaultdict(set)
    for ev in purchases:
        if ev.report_type:
            bought[ev.telegram_id].add(ev.report_type)

    # последнее purchase_completed на (пользователь, report_type)
    latest: dict[tuple[int, str], UserEvent] = {}
    for ev in purchases:
        latest[(ev.telegram_id, ev.report_type)] = ev

    for (tg_id, report_type), ev in latest.items():
        ev_t = _as_utc(ev.created_at)
        age = now - ev_t
        if age < timedelta(hours=24):
            continue
        # куплен ли другой продукт → отмена
        other = bought.get(tg_id, set()) - {report_type}
        if other:
            continue
        await _try_send(
            bot, session, tg_id, f"e6:{report_type}",
            f"push_e6_{report_type}", _open_bot_kb(),
        )


# ─── E7: Купил базовый/расширенный → не купил премиум ─────────────────────────

async def _check_e7(bot, session):
    now = _now()
    purchases = await _fetch_events(session, [PURCHASE_COMPLETED])
    if not purchases:
        return
    # есть ли full для (пользователь, report_type)
    has_full: dict[tuple[int, str], bool] = {}
    for ev in purchases:
        if ev.plan == "full" and ev.report_type:
            has_full[(ev.telegram_id, ev.report_type)] = True

    # последние base/extended на (пользователь, report_type)
    latest: dict[tuple[int, str], UserEvent] = {}
    for ev in purchases:
        if ev.plan in ("base", "extended") and ev.report_type:
            latest[(ev.telegram_id, ev.report_type)] = ev

    for (tg_id, report_type), ev in latest.items():
        if has_full.get((tg_id, report_type)):
            continue
        age = now - _as_utc(ev.created_at)
        ek = f"e7:{report_type}"
        if age >= timedelta(hours=2):
            await _try_send(bot, session, tg_id, f"{ek}:1", "push_e7_1", _open_bot_kb())
        if age >= timedelta(hours=24):
            await _try_send(bot, session, tg_id, f"{ek}:2", "push_e7_2", _open_bot_kb())


# ─── E8: Давно не заходил ─────────────────────────────────────────────────────

def _has_any_report(user: User) -> bool:
    return any([
        user.blocks_json, user.money_blocks_json, user.couple_blocks_json,
    ])


async def _check_e8(bot, session):
    now = _now()
    result = await session.execute(
        select(User).where(
            User.is_blocked.is_(False),
            User.last_activity_at.isnot(None),
        )
    )
    for user in result.scalars():
        if not _has_any_report(user):
            continue
        last = _as_utc(user.last_activity_at)
        age = now - last
        if age >= timedelta(days=7):
            await _try_send(bot, session, user.telegram_id, "e8:1", "push_e8_1", _open_bot_kb())
        if age >= timedelta(days=30):
            await _try_send(bot, session, user.telegram_id, "e8:2", "push_e8_2", _open_bot_kb())


# ─── Sweep ────────────────────────────────────────────────────────────────────

async def run_sweep(bot: Bot) -> None:
    async with async_session() as session:
        await _check_e1(bot, session)
        await _check_e2(bot, session)
        await _check_e3(bot, session)
        await _check_e4(bot, session)
        await _check_e5(bot, session)
        await _check_e6(bot, session)
        await _check_e7(bot, session)
        await _check_e8(bot, session)


async def notification_loop(bot: Bot) -> None:
    log.info("Notification scheduler started")
    last_poll = 0.0
    while True:
        try:
            await run_sweep(bot)
        except Exception:
            log.error("notification sweep failed", exc_info=True)

        loop_time = asyncio.get_running_loop().time()
        if loop_time - last_poll >= 300:  # каждые 5 минут
            try:
                await poll_pending_payments()
            except Exception:
                log.error("payments poll failed", exc_info=True)
            last_poll = loop_time

        await asyncio.sleep(60)
