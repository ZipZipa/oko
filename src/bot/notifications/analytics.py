"""Аналитика для админских команд.

Все метрики считаются на лету из существующих таблиц (users, payments,
user_events, notification_log) — новых таблиц и миграций не требуется.

Разделение как в funnel.py: get_* собирают данные (dict/списки),
format_* превращают их в готовый HTML для отправки в Telegram.
"""
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from sqlalchemy import select

from src.bot.db import async_session
from src.bot.db.models import User, Payment, UserEvent, NotificationLog
from src.bot.config import BASE_PRICES
from src.bot.notifications.events import (
    REGISTRATION_STARTED, PROFILE_COMPLETED, ENTERED_MENU,
    DEMO_SHOWN, PRICING_VIEWED, PAYMENT_INITIATED,
)

_MST = timezone(timedelta(hours=3))

REPORT_LABELS = {"self": "Личность", "money": "Деньги", "couple": "Пара"}
PLAN_LABELS = {"demo": "Демо", "base": "Базовый", "extended": "Расширенный", "full": "Премиум"}

# Сценарии пушей (префикс event_key до ":"), см. scheduler.py
PUSH_SCENARIOS = {
    "e1": "Старт анализа",
    "e2": "Завершение регистрации",
    "e3": "Данные партнёра",
    "e4": "Покупка после демо",
    "e5": "Завершение оплаты",
    "e6": "Кросс-селл",
    "e7": "Апгрейд до Премиум",
    "e8": "Реактивация",
}
_PUSH_ORDER = ["e1", "e2", "e3", "e4", "e5", "e6", "e7", "e8"]


# ─── Утилиты времени ─────────────────────────────────────────────────────────────

def _as_utc_naive(dt):
    """Привести datetime к naive-UTC (как хранится в БД). None → None."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt  # уже наивный UTC
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _period_bounds():
    """Границы периодов в naive-UTC для сравнения с полями БД."""
    now = datetime.now(timezone.utc)
    msk_midnight = now.astimezone(_MST).replace(hour=0, minute=0, second=0, microsecond=0)
    return {
        "today": _as_utc_naive(msk_midnight),
        "7d": _as_utc_naive(now - timedelta(days=7)),
        "30d": _as_utc_naive(now - timedelta(days=30)),
        "now": _as_utc_naive(now),
    }


def _amount(p) -> float:
    try:
        return float(p.amount)
    except (TypeError, ValueError):
        return 0.0


def _pct(part: int, whole: int) -> str:
    return f"{(part / whole * 100):.0f}%" if whole else "—"


def _rub(x: float) -> str:
    return f"{x:,.0f}".replace(",", " ") + " ₽"


def _since(days: int | None):
    """Граница периода в naive-UTC или None (за всё время)."""
    if not days:
        return None
    return _as_utc_naive(datetime.now(timezone.utc) - timedelta(days=days))


def _paid_ts(p):
    return _as_utc_naive(p.paid_at) or _as_utc_naive(p.created_at)


def _fmt_dur(seconds: float) -> str:
    """Длительность в человекочитаемом виде: 45м / 3ч 12м / 2д 4ч."""
    m = int(seconds // 60)
    if m < 60:
        return f"{m}м"
    h, m = divmod(m, 60)
    if h < 24:
        return f"{h}ч {m}м"
    d, h = divmod(h, 24)
    return f"{d}д {h}ч"


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


# ─── 1. Выручка ──────────────────────────────────────────────────────────────────

async def get_revenue_summary() -> dict:
    """Выручка по периодам, продуктам и планам + конверсия оплаты."""
    async with async_session() as session:
        payments = (await session.execute(select(Payment))).scalars().all()

    b = _period_bounds()
    succeeded = [p for p in payments if p.status == "succeeded"]

    def _paid_at(p):
        return _as_utc_naive(p.paid_at) or _as_utc_naive(p.created_at)

    rev = {"today": 0.0, "7d": 0.0, "30d": 0.0, "all": 0.0}
    cnt = {"today": 0, "7d": 0, "30d": 0, "all": 0}
    for p in succeeded:
        amt = _amount(p)
        ts = _paid_at(p)
        rev["all"] += amt
        cnt["all"] += 1
        for key in ("today", "7d", "30d"):
            if ts is not None and ts >= b[key]:
                rev[key] += amt
                cnt[key] += 1

    by_report: dict[str, dict] = defaultdict(lambda: {"sum": 0.0, "count": 0})
    by_plan: dict[str, dict] = defaultdict(lambda: {"sum": 0.0, "count": 0})
    for p in succeeded:
        amt = _amount(p)
        by_report[p.report_type]["sum"] += amt
        by_report[p.report_type]["count"] += 1
        by_plan[p.plan]["sum"] += amt
        by_plan[p.plan]["count"] += 1

    # Конверсия оплаты: платёж создан → оплачен
    initiated = len(payments)
    succeeded_n = len(succeeded)
    abandoned = [p for p in payments if p.status != "succeeded"]
    abandoned_sum = sum(_amount(p) for p in abandoned)

    # Покупки со скидкой: оплачено меньше базовой цены пакета
    disc_count = 0
    disc_rev = 0.0
    disc_lost = 0.0
    for p in succeeded:
        base = BASE_PRICES.get(p.report_type, {}).get(p.plan, 0)
        amt = _amount(p)
        if base and amt < base:
            disc_count += 1
            disc_rev += amt
            disc_lost += base - amt

    avg_check = (rev["all"] / succeeded_n) if succeeded_n else 0.0

    return {
        "rev": rev,
        "cnt": cnt,
        "avg_check": avg_check,
        "by_report": dict(by_report),
        "by_plan": dict(by_plan),
        "initiated": initiated,
        "succeeded": succeeded_n,
        "abandoned": len(abandoned),
        "abandoned_sum": abandoned_sum,
        "disc_count": disc_count,
        "disc_rev": disc_rev,
        "disc_lost": disc_lost,
    }


def format_revenue(d: dict) -> str:
    lines = [
        "💰 <b>Выручка</b>\n",
        f"Сегодня: <b>{_rub(d['rev']['today'])}</b> · {d['cnt']['today']} опл.",
        f"7 дней: <b>{_rub(d['rev']['7d'])}</b> · {d['cnt']['7d']} опл.",
        f"30 дней: <b>{_rub(d['rev']['30d'])}</b> · {d['cnt']['30d']} опл.",
        f"Всего: <b>{_rub(d['rev']['all'])}</b> · {d['cnt']['all']} опл.",
        f"Средний чек: <b>{_rub(d['avg_check'])}</b>",
        "",
        "<b>По продуктам:</b>",
    ]
    for rt in ("self", "money", "couple"):
        if rt in d["by_report"]:
            v = d["by_report"][rt]
            lines.append(f"  {REPORT_LABELS.get(rt, rt)}: {_rub(v['sum'])} · {v['count']} опл.")
    lines.append("")
    lines.append("<b>По планам:</b>")
    for pl in ("base", "extended", "full"):
        if pl in d["by_plan"]:
            v = d["by_plan"][pl]
            lines.append(f"  {PLAN_LABELS.get(pl, pl)}: {_rub(v['sum'])} · {v['count']} опл.")
    lines.append("")
    lines.append(
        f"<b>Конверсия оплаты:</b> {d['succeeded']}/{d['initiated']} "
        f"({_pct(d['succeeded'], d['initiated'])})"
    )
    lines.append(f"<b>Брошено платежей:</b> {d['abandoned']} на {_rub(d['abandoned_sum'])}")
    if d.get("disc_count"):
        lines.append(
            f"<b>Со скидкой:</b> {d['disc_count']} из {d['succeeded']} покупок "
            f"на {_rub(d['disc_rev'])} (недополучено {_rub(d['disc_lost'])})"
        )
    return "\n".join(lines)


# ─── 2. Обзор (dashboard) ─────────────────────────────────────────────────────────

async def get_overview_stats() -> dict:
    """Топ-метрики: пользователи, активность, платящие, выручка за 30 дней."""
    async with async_session() as session:
        users = (await session.execute(select(User))).scalars().all()
        first_seen = (await session.execute(
            select(UserEvent.telegram_id, UserEvent.created_at)
        )).all()
        payments = (await session.execute(
            select(Payment).where(Payment.status == "succeeded")
        )).scalars().all()

    b = _period_bounds()

    # Первое появление пользователя = самое раннее событие (регистрации нет в users)
    earliest: dict[int, datetime] = {}
    for tid, created in first_seen:
        c = _as_utc_naive(created)
        if c is None:
            continue
        if tid not in earliest or c < earliest[tid]:
            earliest[tid] = c

    new_today = sum(1 for c in earliest.values() if c >= b["today"])
    new_7d = sum(1 for c in earliest.values() if c >= b["7d"])
    new_30d = sum(1 for c in earliest.values() if c >= b["30d"])

    active_today = active_7d = 0
    blocked = 0
    for u in users:
        if u.is_blocked:
            blocked += 1
        la = _as_utc_naive(u.last_activity_at)
        if la is not None:
            if la >= b["today"]:
                active_today += 1
            if la >= b["7d"]:
                active_7d += 1

    paying_ids = {p.telegram_id for p in payments}
    rev_30d = sum(
        _amount(p) for p in payments
        if (_as_utc_naive(p.paid_at) or _as_utc_naive(p.created_at) or b["now"]) >= b["30d"]
    )

    return {
        "total_users": len(users),
        "new_today": new_today,
        "new_7d": new_7d,
        "new_30d": new_30d,
        "active_today": active_today,
        "active_7d": active_7d,
        "blocked": blocked,
        "paying": len(paying_ids),
        "rev_30d": rev_30d,
    }


def format_overview(d: dict) -> str:
    total = d["total_users"]
    lines = [
        "📊 <b>Обзор</b>\n",
        f"<b>Пользователей всего:</b> {total}",
        f"  новых: сегодня {d['new_today']} · 7д {d['new_7d']} · 30д {d['new_30d']}",
        "",
        f"<b>Активны:</b> сегодня {d['active_today']} · 7д {d['active_7d']}",
        f"<b>Заблокировали бота:</b> {d['blocked']} ({_pct(d['blocked'], total)})",
        "",
        f"<b>Платящих:</b> {d['paying']} ({_pct(d['paying'], total)} от всех)",
        f"<b>Выручка за 30 дней:</b> {_rub(d['rev_30d'])}",
    ]
    return "\n".join(lines)


# ─── 3. Воронка конверсии ─────────────────────────────────────────────────────────

# "paid" — виртуальный шаг: считается из payments (источник правды),
# а не из событий, т.к. сброс профиля удаляет user_events.
_FUNNEL_STEPS = [
    (REGISTRATION_STARTED, "Начал регистрацию"),
    (PROFILE_COMPLETED, "Заполнил профиль"),
    (ENTERED_MENU, "Вошёл в меню"),
    (DEMO_SHOWN, "Получил демо"),
    (PRICING_VIEWED, "Посмотрел цену"),
    (PAYMENT_INITIATED, "Нажал оплатить"),
    ("paid", "Оплатил"),
]


async def get_conversion_funnel(days: int | None = None) -> list[tuple[str, str, int]]:
    """Число уникальных пользователей, дошедших до каждого шага воронки.

    days — ограничить события последними N днями (None — за всё время).
    Возвращает [(event_type, label, unique_users), ...] в порядке шагов.
    """
    since = _since(days)
    async with async_session() as session:
        stmt = select(UserEvent.event_type, UserEvent.telegram_id)
        if since is not None:
            stmt = stmt.where(UserEvent.created_at >= since)
        rows = (await session.execute(stmt)).all()
        payments = (await session.execute(
            select(Payment).where(Payment.status == "succeeded")
        )).scalars().all()

    users_by_event: dict[str, set[int]] = defaultdict(set)
    for et, tid in rows:
        users_by_event[et].add(tid)

    for p in payments:
        ts = _paid_ts(p)
        if since is None or (ts is not None and ts >= since):
            users_by_event["paid"].add(p.telegram_id)

    return [(et, label, len(users_by_event.get(et, set()))) for et, label in _FUNNEL_STEPS]


def format_conversion(steps: list[tuple[str, str, int]], days: int | None = None) -> str:
    top = steps[0][2] if steps else 0
    period = f"за {days} дн." if days else "за всё время"
    lines = [f"🔻 <b>Воронка конверсии</b> · {period}\n"]
    prev = None
    for _et, label, count in steps:
        from_prev = f" ({_pct(count, prev)} от пред.)" if prev is not None and prev else ""
        lines.append(f"{label}: <b>{count}</b>{from_prev}")
        prev = count
    if steps and top:
        final = steps[-1][2]
        lines.append(f"\n<b>Сквозная конверсия:</b> {_pct(final, top)} (регистрация → оплата)")
    return "\n".join(lines)


# ─── 3б. Медианное время между шагами ────────────────────────────────────────────

async def get_step_timings(days: int | None = None) -> dict:
    """Медианное время (сек) между ключевыми шагами по пользователям,
    прошедшим оба шага: регистрация → демо → нажал оплатить → оплатил.

    Бэкфилл-события (payload_json с маркером backfill) не учитываются —
    их временные метки синтетические."""
    since = _since(days)
    async with async_session() as session:
        stmt = select(UserEvent.telegram_id, UserEvent.event_type, UserEvent.created_at).where(
            UserEvent.event_type.in_([REGISTRATION_STARTED, DEMO_SHOWN, PAYMENT_INITIATED]),
            UserEvent.payload_json.is_(None),
        )
        if since is not None:
            stmt = stmt.where(UserEvent.created_at >= since)
        rows = (await session.execute(stmt)).all()
        payments = (await session.execute(
            select(Payment).where(Payment.status == "succeeded")
        )).scalars().all()

    first: dict[tuple[int, str], datetime] = {}
    for tid, et, created in rows:
        c = _as_utc_naive(created)
        if c is None:
            continue
        key = (tid, et)
        if key not in first or c < first[key]:
            first[key] = c

    first_paid: dict[int, datetime] = {}
    for p in payments:
        ts = _paid_ts(p)
        if ts is None or (since is not None and ts < since):
            continue
        if p.telegram_id not in first_paid or ts < first_paid[p.telegram_id]:
            first_paid[p.telegram_id] = ts

    def _deltas(step_a: str, step_b: str) -> list[float]:
        out = []
        for (tid, et), ta in first.items():
            if et != step_a:
                continue
            tb = first_paid.get(tid) if step_b == "paid" else first.get((tid, step_b))
            if tb is not None and tb >= ta:
                out.append((tb - ta).total_seconds())
        return out

    return {
        "reg_to_demo": _median(_deltas(REGISTRATION_STARTED, DEMO_SHOWN)),
        "demo_to_pay_click": _median(_deltas(DEMO_SHOWN, PAYMENT_INITIATED)),
        "pay_click_to_paid": _median(_deltas(PAYMENT_INITIATED, "paid")),
    }


def format_step_timings(d: dict) -> str:
    labels = [
        ("reg_to_demo", "регистрация → демо"),
        ("demo_to_pay_click", "демо → нажал оплатить"),
        ("pay_click_to_paid", "нажал оплатить → оплатил"),
    ]
    lines = ["⏱ <b>Медианное время между шагами</b>\n"]
    for key, label in labels:
        v = d.get(key)
        lines.append(f"{label}: <b>{_fmt_dur(v) if v is not None else '—'}</b>")
    return "\n".join(lines)


# ─── 3а. Воронка по продуктам ─────────────────────────────────────────────────────

async def get_product_funnel(days: int | None = None) -> dict:
    """Воронка по каждому продукту: демо → цена → нажал оплатить → оплатил.

    Все счётчики — уникальные пользователи. «Оплатил» — из payments
    (источник правды). Для «нажал оплатить» дополнительно: общее число
    попыток и разбивка по планам.
    """
    since = _since(days)
    async with async_session() as session:
        stmt = select(UserEvent.event_type, UserEvent.telegram_id,
                      UserEvent.report_type, UserEvent.plan).where(
            UserEvent.event_type.in_([DEMO_SHOWN, PRICING_VIEWED, PAYMENT_INITIATED]))
        if since is not None:
            stmt = stmt.where(UserEvent.created_at >= since)
        rows = (await session.execute(stmt)).all()
        payments = (await session.execute(
            select(Payment).where(Payment.status == "succeeded")
        )).scalars().all()

    products: dict[str, dict] = defaultdict(lambda: {
        "demo": set(), "pricing": set(), "pay_clicked": set(), "paid": set(),
        "pay_attempts": 0, "plans": defaultdict(set),
    })
    for et, tid, rt, plan in rows:
        if not rt:
            continue  # старые события без report_type — в разрез не попадают
        p = products[rt]
        if et == DEMO_SHOWN:
            p["demo"].add(tid)
        elif et == PRICING_VIEWED:
            p["pricing"].add(tid)
        elif et == PAYMENT_INITIATED:
            p["pay_clicked"].add(tid)
            p["pay_attempts"] += 1
            if plan:
                p["plans"][plan].add(tid)

    for pay in payments:
        ts = _paid_ts(pay)
        if since is None or (ts is not None and ts >= since):
            products[pay.report_type]["paid"].add(pay.telegram_id)

    result: dict[str, dict] = {}
    for rt, p in products.items():
        result[rt] = {
            "demo": len(p["demo"]),
            "pricing": len(p["pricing"]),
            "pay_clicked": len(p["pay_clicked"]),
            "pay_attempts": p["pay_attempts"],
            "paid": len(p["paid"]),
            "plans": {pl: len(tids) for pl, tids in p["plans"].items()},
        }
    return result


def format_product_funnel(d: dict) -> str:
    lines = [
        "🧭 <b>Воронка по продуктам</b>",
        "<i>уникальные пользователи: демо → цена → нажал оплатить → оплатил</i>\n",
    ]
    if not d:
        lines.append("Событий по продуктам пока нет.")
        return "\n".join(lines)
    for rt in ("self", "money", "couple"):
        p = d.get(rt)
        if not p:
            continue
        lines.append(
            f"<b>{REPORT_LABELS.get(rt, rt)}</b>: "
            f"демо {p['demo']} → цена {p['pricing']} ({_pct(p['pricing'], p['demo'])}) "
            f"→ оплата {p['pay_clicked']} ({_pct(p['pay_clicked'], p['pricing'])}) "
            f"→ купил {p['paid']} ({_pct(p['paid'], p['pay_clicked'])})"
        )
        if p["pay_clicked"]:
            plan_bits = [
                f"{PLAN_LABELS.get(pl, pl)} {n} чел."
                for pl in ("base", "extended", "full")
                for n in [p["plans"].get(pl)] if n
            ]
            detail = " · ".join(plan_bits) if plan_bits else "план не зафиксирован"
            lines.append(f"   нажимали: {detail} · попыток {p['pay_attempts']}")
    for rt in d:
        if rt not in ("self", "money", "couple"):
            p = d[rt]
            lines.append(f"<b>{rt}</b>: демо {p['demo']} → оплата {p['pay_clicked']} → купил {p['paid']}")
    return "\n".join(lines)


# ─── 4. Эффективность пушей ───────────────────────────────────────────────────────

def _scenario_of(event_key: str) -> str:
    return event_key.split(":", 1)[0]


# Окна: покупка засчитывается пушу, если случилась в течение 48 ч после
# первого пуша сценария; блокировка — в течение 24 ч после любого пуша.
_PUSH_ATTRIBUTION = timedelta(hours=48)
_PUSH_BLOCK_WINDOW = timedelta(hours=24)


async def get_push_stats() -> dict:
    """По каждому сценарию пушей: получатели, покупки в окне атрибуции,
    блокировки бота вскоре после пуша."""
    async with async_session() as session:
        logs = (await session.execute(
            select(NotificationLog.telegram_id, NotificationLog.event_key, NotificationLog.sent_at)
        )).all()
        purchases = (await session.execute(
            select(Payment).where(Payment.status == "succeeded")
        )).scalars().all()
        blocked_rows = (await session.execute(
            select(User.telegram_id, User.blocked_at)
            .where(User.is_blocked.is_(True), User.blocked_at.isnot(None))
        )).all()

    # Покупки по пользователю (naive-UTC, из payments — источник правды)
    buys_by_user: dict[int, list[datetime]] = defaultdict(list)
    for p in purchases:
        ts = _paid_ts(p)
        if ts is not None:
            buys_by_user[p.telegram_id].append(ts)

    blocked_at: dict[int, datetime] = {}
    for tid, ba in blocked_rows:
        b = _as_utc_naive(ba)
        if b is not None:
            blocked_at[tid] = b

    # Все отправки каждого сценария каждому пользователю
    sends: dict[str, dict[int, list[datetime]]] = defaultdict(lambda: defaultdict(list))
    sends_total: dict[str, int] = defaultdict(int)
    for tid, ek, sent_at in logs:
        sc = _scenario_of(ek)
        sends_total[sc] += 1
        s = _as_utc_naive(sent_at)
        if s is not None:
            sends[sc][tid].append(s)

    result: dict[str, dict] = {}
    for sc, users in sends.items():
        recipients = len(users)
        converted = 0
        blocked = 0
        for tid, times in users.items():
            first = min(times)
            if any(first <= t <= first + _PUSH_ATTRIBUTION for t in buys_by_user.get(tid, [])):
                converted += 1
            ba = blocked_at.get(tid)
            if ba is not None and any(s <= ba <= s + _PUSH_BLOCK_WINDOW for s in times):
                blocked += 1
        result[sc] = {
            "sends": sends_total.get(sc, 0),
            "recipients": recipients,
            "converted": converted,
            "blocked": blocked,
        }
    return result


def format_push_stats(d: dict) -> str:
    lines = [
        "📨 <b>Эффективность пушей</b>",
        "<i>получатели → купили в течение 48 ч · 🚫 заблокировали в течение 24 ч</i>\n",
    ]
    keys = [k for k in _PUSH_ORDER if k in d] + [k for k in d if k not in _PUSH_ORDER]
    if not keys:
        lines.append("Пуши пока не отправлялись.")
        return "\n".join(lines)
    for sc in keys:
        v = d[sc]
        name = PUSH_SCENARIOS.get(sc, sc)
        line = (
            f"<b>{sc}</b> {name}: {v['recipients']} → {v['converted']} "
            f"({_pct(v['converted'], v['recipients'])}) · отправок {v['sends']}"
        )
        if v.get("blocked"):
            line += f" · 🚫 {v['blocked']}"
        lines.append(line)
    return "\n".join(lines)


# ─── 5. Реферальная сводка ────────────────────────────────────────────────────────

async def get_referral_summary() -> dict:
    """Топ рефереров + конверсия приглашённых в оплату и суммарная выручка."""
    async with async_session() as session:
        owners = (await session.execute(
            select(User).where(User.referral_code.isnot(None))
        )).scalars().all()
        referred = (await session.execute(
            select(User).where(User.referred_by.isnot(None))
        )).scalars().all()

        referred_tids = [u.telegram_id for u in referred]
        if referred_tids:
            payments = (await session.execute(
                select(Payment).where(
                    Payment.telegram_id.in_(referred_tids),
                    Payment.status == "succeeded",
                )
            )).scalars().all()
        else:
            payments = []

    code_to_tids: dict[str, list[int]] = defaultdict(list)
    for u in referred:
        code_to_tids[u.referred_by].append(u.telegram_id)

    pay_by_tid: dict[int, list] = defaultdict(list)
    for p in payments:
        pay_by_tid[p.telegram_id].append(p)

    rows = []
    for owner in owners:
        tids = code_to_tids.get(owner.referral_code)
        if not tids:
            continue
        paid_users = sum(1 for t in tids if pay_by_tid.get(t))
        revenue = sum(_amount(p) for t in tids for p in pay_by_tid.get(t, []))
        rows.append({
            "name": owner.name or "—",
            "telegram_id": owner.telegram_id,
            "code": owner.referral_code,
            "invited": len(tids),
            "paid_users": paid_users,
            "revenue": revenue,
        })
    rows.sort(key=lambda r: -r["invited"])

    total_invited = len(referred)
    total_paid_users = sum(1 for t in referred_tids if pay_by_tid.get(t))
    total_revenue = sum(_amount(p) for p in payments)

    return {
        "rows": rows,
        "total_invited": total_invited,
        "total_paid_users": total_paid_users,
        "total_revenue": total_revenue,
    }


def format_referral(d: dict) -> str:
    if not d["rows"]:
        return "🔗 <b>Реферальная статистика</b>\n\nПока никто не пришёл по реферальным ссылкам."

    lines = ["🔗 <b>Реферальная статистика</b>\n"]
    for r in d["rows"]:
        lines.append(
            f"👤 <b>{r['name']}</b> (id: <code>{r['telegram_id']}</code>)\n"
            f"   Код: <code>{r['code']}</code>\n"
            f"   Приглашено: {r['invited']} · оплатили: {r['paid_users']} "
            f"({_pct(r['paid_users'], r['invited'])})\n"
            f"   Выручка: {_rub(r['revenue'])}\n"
        )
    lines.append(
        f"\n<b>Итого:</b> {d['total_invited']} приглашённых · "
        f"оплатили {d['total_paid_users']} ({_pct(d['total_paid_users'], d['total_invited'])}) · "
        f"{_rub(d['total_revenue'])}"
    )
    return "\n".join(lines)
