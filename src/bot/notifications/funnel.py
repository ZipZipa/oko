"""Воронка пользователя: вычисление стадии и форматирование карточек.

Стадия — производное от состояния (events + payments + last_activity),
не хранится, а считается на лету. Логика совпадает с SQL-запросами
из ручного тестирования и с условиями планировщика.
"""
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from sqlalchemy import select

from src.bot.db import async_session
from src.bot.db.models import User, Payment, UserEvent, NotificationLog
from src.bot.notifications.events import (
    REGISTRATION_STARTED, PROFILE_COMPLETED, ENTERED_MENU,
    COUPLE_PARTNER_STARTED, COUPLE_PARTNER_COMPLETED,
    DEMO_SHOWN, PURCHASE_COMPLETED,
)

_PLAN_ORDER = {"base": 1, "extended": 2, "full": 3}
_MST = timezone(timedelta(hours=3))

STAGE_LABELS = {
    "new": "Новый",
    "registering": "На регистрации",
    "menu_idle": "В меню, без действия",
    "couple_pending": "Ввод данных партнёра",
    "demo_seen": "Демо получено",
    "paying": "Ожидает оплаты",
    "bought": "Купил",
    "inactive": "Неактивен",
    "unknown_activity": "Нет данных активности",
    "blocked": "Заблокировал бота",
}

# Подсказка, какие пуши актуальны для стадии
STAGE_SCENARIOS = {
    "new": "—",
    "registering": "E2: напоминание о завершении регистрации",
    "menu_idle": "E1: пуш о старте анализа",
    "couple_pending": "E3: пуш о данных партнёра",
    "demo_seen": "E4: пуш о покупке полного разбора",
    "paying": "E5: пуш о завершении оплаты",
    "bought": "E6: кросс-селл · E7: апгрейд до Премиум",
    "inactive": "E8: реактивация",
    "unknown_activity": "—",
    "blocked": "пуши не отправляются",
}

_STAGE_ORDER = [
    "new", "registering", "menu_idle", "couple_pending",
    "demo_seen", "paying", "bought", "inactive",
    "unknown_activity", "blocked",
]


def _as_utc(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _is_complete(u: User) -> bool:
    return bool(u.name and u.face_json and u.birth_date)


def _fmt_dt(dt) -> str:
    if not dt:
        return "—"
    return _as_utc(dt).astimezone(_MST).strftime("%d.%m.%Y %H:%M")


def _compute_stage(u, latest: dict, has_demo: bool, has_bought: bool,
                   has_pending: bool, last_act, days_inactive) -> str:
    if u.is_blocked:
        return "blocked"
    # inactive имеет приоритет над конверсионными стадиями — это цель E8
    # (пользователь ушёл, независимо от того, покупал ли раньше)
    if last_act is not None and days_inactive is not None and days_inactive >= 7:
        return "inactive"
    if has_pending:
        return "paying"
    if has_bought:
        return "bought"
    if has_demo:
        return "demo_seen"
    if latest.get(COUPLE_PARTNER_STARTED) and not latest.get(COUPLE_PARTNER_COMPLETED):
        return "couple_pending"
    if latest.get(ENTERED_MENU) and _is_complete(u):
        return "menu_idle"
    if latest.get(REGISTRATION_STARTED):
        return "registering"
    if last_act is None:
        return "unknown_activity"
    return "new"


async def get_user_funnel(telegram_id: int) -> dict | None:
    """Собрать карточку воронки для пользователя."""
    async with async_session() as session:
        u = (await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )).scalar_one_or_none()
        if not u:
            return None

        evs = (await session.execute(
            select(UserEvent).where(UserEvent.telegram_id == telegram_id)
            .order_by(UserEvent.created_at.asc())
        )).scalars().all()

        pending = (await session.execute(
            select(Payment).where(
                Payment.telegram_id == telegram_id,
                Payment.status == "pending",
            )
        )).scalars().all()

        logs = (await session.execute(
            select(NotificationLog).where(NotificationLog.telegram_id == telegram_id)
            .order_by(NotificationLog.sent_at.asc())
        )).scalars().all()

    latest: dict[str, UserEvent] = {}
    for e in evs:
        latest[e.event_type] = e  # evs отсортированы по возрастанию

    demos = sorted({
        e.report_type for e in evs
        if e.event_type == DEMO_SHOWN and e.report_type
    })

    # высший план на каждый report_type
    bought: dict[str, str] = {}
    for e in evs:
        if e.event_type == PURCHASE_COMPLETED and e.report_type:
            cur = bought.get(e.report_type)
            if cur is None or _PLAN_ORDER.get(e.plan, 0) > _PLAN_ORDER.get(cur, 0):
                bought[e.report_type] = e.plan

    last_act = _as_utc(u.last_activity_at)
    days_inactive = (datetime.now(timezone.utc) - last_act).days if last_act else None
    stage = _compute_stage(
        u, latest, bool(demos), bool(bought), bool(pending), last_act, days_inactive,
    )

    def _t(key):
        ev = latest.get(key)
        return _as_utc(ev.created_at) if ev else None

    return {
        "telegram_id": u.telegram_id,
        "name": u.name,
        "profile_ok": _is_complete(u),
        "is_blocked": u.is_blocked,
        "last_activity_at": last_act,
        "days_inactive": days_inactive,
        "reg_started": _t(REGISTRATION_STARTED),
        "profile_done": _t(PROFILE_COMPLETED),
        "entered_menu": _t(ENTERED_MENU),
        "couple_started": _t(COUPLE_PARTNER_STARTED),
        "couple_done": _t(COUPLE_PARTNER_COMPLETED),
        "demos": demos,
        "bought": bought,
        "pending_count": len(pending),
        "pending_since": _as_utc(max((p.created_at for p in pending))) if pending else None,
        "sent": [l.event_key for l in logs],
        "stage": stage,
    }


async def get_funnel_distribution() -> list[tuple[str, int]]:
    """Распределение всех пользователей по стадиям."""
    async with async_session() as session:
        users = (await session.execute(select(User))).scalars().all()
        all_evs = (await session.execute(select(UserEvent))).scalars().all()
        pend_ids = (await session.execute(
            select(Payment.telegram_id).where(Payment.status == "pending")
        )).scalars().all()

    pend_set = set(pend_ids)
    evs_by_user: dict[int, list[UserEvent]] = defaultdict(list)
    for e in all_evs:
        evs_by_user[e.telegram_id].append(e)

    counts: dict[str, int] = defaultdict(int)
    for u in users:
        evs = evs_by_user.get(u.telegram_id, [])
        latest: dict[str, UserEvent] = {}
        for e in evs:
            latest[e.event_type] = e
        has_demo = any(e.event_type == DEMO_SHOWN for e in evs)
        has_bought = any(e.event_type == PURCHASE_COMPLETED for e in evs)
        has_pending = u.telegram_id in pend_set
        last_act = _as_utc(u.last_activity_at)
        days_inactive = (datetime.now(timezone.utc) - last_act).days if last_act else None
        counts[_compute_stage(
            u, latest, has_demo, has_bought, has_pending, last_act, days_inactive,
        )] += 1

    ordered = [(s, counts.get(s, 0)) for s in _STAGE_ORDER if counts.get(s, 0) > 0]
    extras = [(s, counts[s]) for s in counts if s not in set(_STAGE_ORDER)]
    return ordered + extras


def format_user_card(d: dict) -> str:
    bought_str = ", ".join(f"{rt}:{pl}" for rt, pl in d["bought"].items()) or "—"
    demos_str = ", ".join(d["demos"]) or "—"
    sent_str = ", ".join(d["sent"]) if d["sent"] else "пока ничего не отправлено"
    lines = [
        f"👁 <b>Воронка пользователя</b>",
        f"<b>{d['name'] or '—'}</b> · id: <code>{d['telegram_id']}</code>",
        f"",
        f"<b>Стадия:</b> {STAGE_LABELS.get(d['stage'], d['stage'])}",
        f"<b>Профиль заполнен:</b> {'да' if d['profile_ok'] else 'нет'}",
        f"<b>Активность:</b> {_fmt_dt(d['last_activity_at'])}"
        + (f" · неактивен {d['days_inactive']} дн." if d['days_inactive'] is not None else ""),
        f"<b>Заблокирован:</b> {'да' if d['is_blocked'] else 'нет'}",
        f"",
        f"<b>Демо получены:</b> {demos_str}",
        f"<b>Куплено:</b> {bought_str}",
        f"<b>Pending-платежей:</b> {d['pending_count']}"
        + (f" (с {_fmt_dt(d['pending_since'])})" if d['pending_count'] else ""),
        f"",
        f"<b>События:</b>",
        f"  регистрация: {_fmt_dt(d['reg_started'])}",
        f"  профиль готов: {_fmt_dt(d['profile_done'])}",
        f"  вход в меню: {_fmt_dt(d['entered_menu'])}",
        f"  партнёр: {_fmt_dt(d['couple_started'])} → {_fmt_dt(d['couple_done'])}",
        f"",
        f"<b>Отправленные пуши:</b> {sent_str}",
        f"<b>Актуально:</b> {STAGE_SCENARIOS.get(d['stage'], '—')}",
    ]
    return "\n".join(lines)


def format_distribution(dist: list[tuple[str, int]]) -> str:
    total = sum(c for _, c in dist)
    lines = ["<b>Воронка — распределение по стадиям</b>\n"]
    for stage, count in dist:
        pct = (count / total * 100) if total else 0
        lines.append(f"• {STAGE_LABELS.get(stage, stage)}: <b>{count}</b> ({pct:.0f}%)")
    lines.append(f"\n<b>Всего:</b> {total}")
    return "\n".join(lines)
