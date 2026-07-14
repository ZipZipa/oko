"""Одноразовый бэкфилл недостающих ранних событий воронки.

У пользователей, пришедших до появления логирования событий (или сбросивших
профиль), нет ранних записей в user_events — из-за этого шаги воронки
не вложены друг в друга («Вошёл в меню» > 100% от «Заполнил профиль»).

Скрипт дописывает недостающие события по фактическому состоянию:
  - registration_started — каждому пользователю (раз он есть в users);
  - profile_completed, entered_menu — если профиль заполнен или была покупка;
  - demo_shown, pricing_viewed, payment_initiated — по succeeded-платежам;
  - pricing_viewed — тем, у кого есть реальный payment_initiated
    (кнопка «Купить» живёт на экране с ценой).

Все вставленные строки помечены payload_json='{"backfill": true}':
их игнорирует статистика таймингов и их можно удалить одним запросом:
  DELETE FROM user_events WHERE payload_json LIKE '%backfill%';

Запуск (из корня проекта, тем же окружением, что и бот):
  python -m scripts.backfill_events           # dry-run, только печать
  python -m scripts.backfill_events --apply   # записать в БД
"""
import asyncio
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from sqlalchemy import select

from src.bot.db import async_session
from src.bot.db.models import User, Payment, UserEvent
from src.bot.notifications.events import (
    REGISTRATION_STARTED, PROFILE_COMPLETED, ENTERED_MENU,
    DEMO_SHOWN, PRICING_VIEWED, PAYMENT_INITIATED,
)

BACKFILL_MARK = '{"backfill": true}'


def _naive_utc(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _is_complete(u: User) -> bool:
    return bool(u.name and u.face_json and u.birth_date)


async def collect_inserts() -> list[UserEvent]:
    async with async_session() as session:
        users = (await session.execute(select(User))).scalars().all()
        events = (await session.execute(select(UserEvent))).scalars().all()
        payments = (await session.execute(
            select(Payment).where(Payment.status == "succeeded")
        )).scalars().all()

    evs_by_user: dict[int, list[UserEvent]] = defaultdict(list)
    for e in events:
        evs_by_user[e.telegram_id].append(e)
    pays_by_user: dict[int, list[Payment]] = defaultdict(list)
    for p in payments:
        pays_by_user[p.telegram_id].append(p)

    inserts: list[UserEvent] = []

    def _add(tid, event_type, ts, report_type=None, plan=None, payment_id=None):
        inserts.append(UserEvent(
            telegram_id=tid, event_type=event_type,
            report_type=report_type, plan=plan, payment_id=payment_id,
            created_at=ts, payload_json=BACKFILL_MARK,
        ))

    for u in users:
        tid = u.telegram_id
        evs = evs_by_user.get(tid, [])
        pays = pays_by_user.get(tid, [])
        has = lambda et: any(e.event_type == et for e in evs)
        has_rt = lambda et, rt: any(
            e.event_type == et and e.report_type == rt for e in evs
        )

        # Якорь — самый ранний след пользователя; фейки встают до него,
        # чтобы не искажать периодные срезы (/funnelstats N).
        traces = (
            [_naive_utc(e.created_at) for e in evs]
            + [_naive_utc(p.created_at) for p in pays]
            + [_naive_utc(u.last_activity_at)]
        )
        traces = [t for t in traces if t is not None]
        if not traces:
            continue  # пользователь без единого следа — нечего восстанавливать
        anchor = min(traces)

        bought = bool(pays)
        if not has(REGISTRATION_STARTED):
            _add(tid, REGISTRATION_STARTED, anchor - timedelta(seconds=3))
        if _is_complete(u) or bought:
            if not has(PROFILE_COMPLETED):
                _add(tid, PROFILE_COMPLETED, anchor - timedelta(seconds=2))
            if not has(ENTERED_MENU):
                _add(tid, ENTERED_MENU, anchor - timedelta(seconds=1))

        # По succeeded-платежам: демо, экран цены и нажатие «оплатить»
        for p in pays:
            pts = _naive_utc(p.created_at) or anchor
            if not has_rt(DEMO_SHOWN, p.report_type):
                _add(tid, DEMO_SHOWN, pts - timedelta(seconds=2), report_type=p.report_type)
            if not has_rt(PRICING_VIEWED, p.report_type):
                _add(tid, PRICING_VIEWED, pts - timedelta(seconds=1),
                     report_type=p.report_type, plan=p.plan)
            if not any(e.event_type == PAYMENT_INITIATED and e.payment_id == p.yookassa_id
                       for e in evs):
                _add(tid, PAYMENT_INITIATED, pts,
                     report_type=p.report_type, plan=p.plan, payment_id=p.yookassa_id)
            # чтобы has_rt видел только что добавленное и не дублировал
            evs = evs + [i for i in inserts if i.telegram_id == tid]

        # Реальный клик «оплатить» без просмотра цены не бывает —
        # кнопка «Купить» находится на экране пакета с ценой.
        for e in list(evs):
            if e.event_type == PAYMENT_INITIATED and e.report_type:
                if not has_rt(PRICING_VIEWED, e.report_type):
                    _add(tid, PRICING_VIEWED,
                         _naive_utc(e.created_at) - timedelta(seconds=1),
                         report_type=e.report_type, plan=e.plan)
                    evs = evs + [inserts[-1]]

    return inserts


async def main():
    apply = "--apply" in sys.argv
    inserts = await collect_inserts()

    by_type: dict[str, int] = defaultdict(int)
    for i in inserts:
        by_type[i.event_type] += 1

    print(f"К вставке: {len(inserts)} событий "
          f"({'ЗАПИСЬ' if apply else 'dry-run, добавьте --apply'})")
    for et, n in sorted(by_type.items()):
        print(f"  {et}: {n}")
    for i in inserts:
        print(f"  tg={i.telegram_id} {i.event_type}"
              f"{' ' + i.report_type if i.report_type else ''}"
              f"{'/' + i.plan if i.plan else ''} @ {i.created_at}")

    if apply and inserts:
        async with async_session() as session:
            session.add_all(inserts)
            await session.commit()
        print("Записано.")


if __name__ == "__main__":
    asyncio.run(main())
