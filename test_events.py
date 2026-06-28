"""
Тесты и документация системы пушей (воронки конверсии) ОКО.

Этот файл одновременно:
  1) документирует, как устроена система пушей;
  2) проверяет все сценарии E1–E8: срабатывание, отмену, идемпотентность;
  3) проверяет логирование событий и вычисление стадии воронки.

Запуск:
    .venv/bin/python test_events.py

Все тесты идут на изолированной временной SQLite-БД (env DATABASE_URL
перекрывается до импорта src.bot.db), реальный бот и YooKassa не нужны.
Отправка сообщений заменена на MockBot, который фиксирует «улетевшие» пуши.

────────────────────────────────────────────────────────────────────────────
АРХИТЕКТУРА СИСТЕМЫ ПУШЕЙ
────────────────────────────────────────────────────────────────────────────

Таблицы (src/bot/db/models.py):
  • user_events        — append-only лог событий пользователя.
  • notification_log   — журнал отправленных пушей (идемпотентность).
                         UNIQUE(telegram_id, event_key).
  • users.last_activity_at / users.is_blocked — состояние для E8 и блокировок.
  • payments           — платежи YooKassa (status, created_at, paid_at).

Поток данных:
  handlers.py  ──log_event()──►  user_events
                                    │
  scheduler.py (sweep раз в 60с) ──► читает user_events + payments + users,
                                    │ вычисляет, кому что пора отправить,
                                    │ проверяет условия отмены,
                                    ▼
  bot.send_message ──► notification_log (чтобы не отправить повторно)

Типы событий (src/bot/notifications/events.py):
  registration_started        — E2: пользователь нажал /start (новый).
  profile_completed           — E2 отмена: профиль стал полным
                                (name + face_json + birth_date).
  entered_menu                — E1: пользователь дошёл до главного меню
                                с полным профилем.
  couple_partner_started      — E3: нажал «Совместимость → Запустить анализ».
  couple_partner_completed    — E3 отмена: ввёл данные партнёра (фото принято).
  demo_shown                  — E4: демо-отчёт сгенерирован и сохранён.
  payment_initiated           — E5: создан платёж (pending).
  purchase_completed          — E4 отмена / E6 / E7: оплата подтверждена.

Ключи пушей (event_key в notification_log):
  E1:  e1:1, e1:2
  E2:  e2:1, e2:2
  E3:  e3:1, e3:2
  E4:  e4:{report_type}:1  e4:{report_type}:2  e4:{report_type}:3
       report_type ∈ {self, money, couple}
  E5:  e5:{yookassa_id}:1  e5:{yookassa_id}:2  e5:{yookassa_id}:3
  E6:  e6:{report_type}                       (один пуш на купленный продукт)
  E7:  e7:{report_type}:1  e7:{report_type}:2
  E8:  e8:1, e8:2

Тайминги и тексты — в src/bot/messages.py (push_e1_1 … push_e8_2).

УСЛОВИЯ ОТМЕНЫ (важно для тестов):
  E1 отменяется, если пользователь КОГДА-ЛИБО начинал анализ
     (demo_shown / payment_initiated / couple_partner_started /
     purchase_completed). Не «после последнего входа в меню», а именно
     когда-либо — иначе повторный вход в меню реактивирует E1.
  E2 отменяется profile_completed после registration_started.
  E3 отменяется couple_partner_completed после couple_partner_started.
  E4 отменяется purchase_completed ИЛИ payment_initiated для того же
     report_type после demo_shown.
  E5 отменяется, когда платеж стал succeeded (sweep берёт только pending).
  E6 отменяется, если куплен другой продукт (другой report_type).
  E7 отменяется, если для того же report_type куплен plan='full'.
  E8 отменяется любой активностью (middleware обновляет last_activity_at
     и чистит e8:* из notification_log).

ИДЕМПОТЕНТНОСТЬ: повторный sweep не дублирует пуши — отправка идёт только
если в notification_log нет строки с таким event_key.
"""
import asyncio
import os
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── Изолированная БД: перекрываем DATABASE_URL ДО импорта src.bot.db ──────────
_TMPDB = tempfile.mktemp(suffix=".db")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMPDB}"
os.environ["BOT_TOKEN"] = "x"
os.environ["BOT_USERNAME"] = "okotestbot"
os.environ.setdefault("YOOKASSA_SHOP_ID", "x")
os.environ.setdefault("YOOKASSA_SECRET_KEY", "x")

sys.path.insert(0, str(Path(__file__).parent))

import datetime as _dt  # noqa: E402

from sqlalchemy import delete, select  # noqa: E402

from src.bot.db.session import init_db, engine, async_session  # noqa: E402
from src.bot.db.models import User, Payment, UserEvent, NotificationLog  # noqa: E402
from src.bot.messages import MESSAGES  # noqa: E402
from src.bot.notifications.events import (  # noqa: E402
    log_event, log_event_once, mark_purchase_completed, reset_notification_state,
    REGISTRATION_STARTED, PROFILE_COMPLETED, ENTERED_MENU,
    COUPLE_PARTNER_STARTED, COUPLE_PARTNER_COMPLETED,
    DEMO_SHOWN, PAYMENT_INITIATED, PURCHASE_COMPLETED,
)
from src.bot.notifications.scheduler import run_sweep  # noqa: E402
from src.bot.notifications.funnel import (  # noqa: E402
    get_user_funnel, get_funnel_distribution, STAGE_LABELS,
)

# Имена типов событий для читаемости тестов
EVT = {
    "reg_started": REGISTRATION_STARTED,
    "profile_done": PROFILE_COMPLETED,
    "entered_menu": ENTERED_MENU,
    "couple_started": COUPLE_PARTNER_STARTED,
    "couple_done": COUPLE_PARTNER_COMPLETED,
    "demo": DEMO_SHOWN,
    "pay_init": PAYMENT_INITIATED,
    "purchase": PURCHASE_COMPLETED,
}


# ─── MockBot: вместо Telegram фиксируем отправленные сообщения ────────────────

class MockBot:
    """Заглушка aiogram.Bot: запоминает все «отправленные» сообщения.

    При TelegramForbiddenError (имитация блокировки) реальный бот помечает
    пользователя is_blocked=True; здесь это не нужно — мы просто считаем sends.
    """

    def __init__(self):
        self.sent: list[tuple[int, str]] = []  # (telegram_id, text)

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))
        return None

    def texts_for(self, tg: int) -> list[str]:
        return [t for cid, t in self.sent if cid == tg]

    def reset(self):
        self.sent.clear()


# ─── Хелперы сидирования ──────────────────────────────────────────────────────

def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def clean():
    """Очистка всех таблиц между тестами для изоляции."""
    async with async_session() as s:
        await s.execute(delete(UserEvent))
        await s.execute(delete(NotificationLog))
        await s.execute(delete(Payment))
        await s.execute(delete(User))
        await s.commit()


async def add_user(tg: int, *, name="Test", face=True, birth=True,
                   blocked=False, last_activity=None, reports=()):
    """Создать пользователя. face/birth=False — профиль неполный.
    reports — кортеж из 'self'/'money'/'couple' чтобы заполнить *_blocks_json.
    """
    async with async_session() as s:
        u = User(
            telegram_id=tg,
            name=name if name else None,
            face_json="{}" if face else None,
            birth_date=_dt.date(2000, 1, 1) if birth else None,
            is_blocked=blocked,
            last_activity_at=last_activity,
        )
        if "self" in reports:
            u.blocks_json = "{}"
        if "money" in reports:
            u.money_blocks_json = "{}"
        if "couple" in reports:
            u.couple_blocks_json = "{}"
        s.add(u)
        await s.commit()


async def add_event(tg: int, event_type: str, age: timedelta, **kw):
    """Записать событие с created_at = now - age (симуляция прошествия времени)."""
    async with async_session() as s:
        s.add(UserEvent(
            telegram_id=tg, event_type=event_type,
            created_at=datetime.now(timezone.utc) - age, **kw,
        ))
        await s.commit()


async def add_payment(tg: int, yoo_id: str, *, status="pending", age=timedelta(0),
                      report_type="self", plan="base"):
    async with async_session() as s:
        s.add(Payment(
            yookassa_id=yoo_id, telegram_id=tg, report_type=report_type,
            plan=plan, amount="249.00", status=status,
            confirmation_url=f"https://pay.example/{yoo_id}",
            created_at=datetime.now(timezone.utc) - age,
        ))
        await s.commit()


async def logged_keys(tg: int) -> list[str]:
    """Список event_key, уже записанных в notification_log для пользователя."""
    async with async_session() as s:
        r = await s.execute(
            select(NotificationLog.event_key)
            .where(NotificationLog.telegram_id == tg)
            .order_by(NotificationLog.sent_at)
        )
        return list(r.scalars().all())


def push_text(key: str) -> str:
    return MESSAGES[key].text


# ═════════════════════════════════════════════════════════════════════════════
# ТЕСТЫ: ЛОГИРОВАНИЕ СОБЫТИЙ
# ═════════════════════════════════════════════════════════════════════════════

async def test_log_event_writes_row():
    """log_event всегда добавляет новую строку в user_events."""
    await add_user(1)
    await log_event(1, ENTERED_MENU)
    await log_event(1, ENTERED_MENU)
    async with async_session() as s:
        r = await s.execute(select(UserEvent).where(UserEvent.telegram_id == 1))
        rows = r.scalars().all()
    assert len(rows) == 2, f"ожидал 2 строки, получил {len(rows)}"


async def test_log_event_once_is_idempotent():
    """log_event_once пишет событие один раз; повторный вызов — no-op."""
    await add_user(2)
    first = await log_event_once(2, PROFILE_COMPLETED)
    second = await log_event_once(2, PROFILE_COMPLETED)
    assert first is True, "первый вызов должен записать"
    assert second is False, "повторный вызов не должен дублировать"
    async with async_session() as s:
        r = await s.execute(
            select(UserEvent).where(
                UserEvent.telegram_id == 2, UserEvent.event_type == PROFILE_COMPLETED,
            )
        )
        assert len(r.scalars().all()) == 1


async def test_log_event_once_scoped_by_report_type():
    """log_event_once учитывает report_type: demo_shown для self и money независимы."""
    await add_user(3)
    await log_event_once(3, DEMO_SHOWN, report_type="self")
    r2 = await log_event_once(3, DEMO_SHOWN, report_type="money")
    assert r2 is True, "demo_shown для другого report_type должен записаться"


async def test_mark_purchase_completed_idempotent_by_payment_id():
    """mark_purchase_completed идемпотентен по payment_id (одна покупка = одна запись)."""
    await add_user(4)
    await mark_purchase_completed(4, "self", "base", "pay_X")
    await mark_purchase_completed(4, "self", "base", "pay_X")  # повтор
    await mark_purchase_completed(4, "self", "full", "pay_Y")  # другой платёж
    async with async_session() as s:
        r = await s.execute(
            select(UserEvent).where(
                UserEvent.telegram_id == 4,
                UserEvent.event_type == PURCHASE_COMPLETED,
            )
        )
        rows = r.scalars().all()
    assert len(rows) == 2, f"ожидал 2 покупки, получил {len(rows)}"


async def test_reset_notification_state_clears_and_restarts():
    """reset_notification_state удаляет все события и логи, затем логирует
    свежий registration_started — воронка перезапускается с нуля (сценарий «Начать заново»).
    """
    await add_user(5)
    await log_event(5, ENTERED_MENU)
    await log_event(5, DEMO_SHOWN, report_type="self")
    async with async_session() as s:
        s.add(NotificationLog(telegram_id=5, event_key="e1:1"))
        await s.commit()

    await reset_notification_state(5)

    async with async_session() as s:
        ev = (await s.execute(select(UserEvent).where(UserEvent.telegram_id == 5))).scalars().all()
        lg = (await s.execute(select(NotificationLog).where(NotificationLog.telegram_id == 5))).scalars().all()
    assert len(ev) == 1 and ev[0].event_type == REGISTRATION_STARTED
    assert len(lg) == 0


# ═════════════════════════════════════════════════════════════════════════════
# ТЕСТЫ: СЦЕНАРИИ ПУШЕЙ E1–E8
# ═════════════════════════════════════════════════════════════════════════════

async def test_e1_entered_menu_idle_fires_and_cancel():
    """E1. Зашёл в меню с полным профилем → ничего не начал.

    Пуш 1 — через 15 минут: «Твой персональный анализ ещё не начат.»
    Пуш 2 — через 24 часа: «Ответы о тебе всё ещё ждут тебя в ОКО.»

    Отмена: после entered_menu появился demo_shown.
    """
    bot = MockBot()

    # кандидат: entered_menu 20 мин назад
    await add_user(1001)
    await add_event(1001, ENTERED_MENU, timedelta(minutes=20))
    # отмена: после entered_menu запустили демо
    await add_user(1002)
    await add_event(1002, ENTERED_MENU, timedelta(minutes=20))
    await add_event(1002, DEMO_SHOWN, timedelta(minutes=10), report_type="self")

    await run_sweep(bot)

    assert push_text("push_e1_1") in bot.texts_for(1001), "E1:1 должен прийти"
    assert not bot.texts_for(1002), "E1 должен отменяться demo_shown"

    # второй пуш — через 24ч
    bot.reset()
    await clean()
    await add_user(1001)
    await add_event(1001, ENTERED_MENU, timedelta(hours=25))
    await run_sweep(bot)
    assert push_text("push_e1_2") in bot.texts_for(1001), "E1:2 должен прийти"


async def test_e1_no_fire_on_reentry_after_conversion():
    """Регрессия: пользователь УЖЕ получил демо, затем повторно зашёл в меню —
    E1 не должен срабатывать.

    Раньше отмена E1 проверяла «конверсия после последнего entered_menu».
    Повторный вход в меню (/start, «← В меню») перезаписывал entered_menu
    свежим временем, демо оказывались «до» него — и E1 ложно стрелял для
    уже конвертированного пользователя. Теперь E1 проверяет «когда-либо
    начинал анализ», поэтому повторный вход его не реактивирует.
    """
    bot = MockBot()
    await add_user(1050)
    # сначала демо (конверсия), потом повторный вход в меню (свежее событие)
    await add_event(1050, DEMO_SHOWN, timedelta(minutes=30), report_type="self")
    await add_event(1050, ENTERED_MENU, timedelta(minutes=20))
    await run_sweep(bot)
    # E4 по демо может легитимно прийти — проверяем именно отсутствие E1
    assert push_text("push_e1_1") not in bot.texts_for(1050), (
        "E1 не должен срабатывать, если пользователь уже начинал анализ"
    )
    assert push_text("push_e1_2") not in bot.texts_for(1050)


async def test_e2_registration_abandoned_fires_and_cancel():
    """E2. Начал регистрацию → бросил на заполнении данных.

    Пуш 1 — через 30 минут: «Ты почти начал анализ. Остался последний шаг.»
    Пуш 2 — через 12 часов: «Дополни данные и получи свой персональный разбор.»

    Отмена: profile_completed после registration_started.
    """
    bot = MockBot()
    await add_user(2001, face=False, birth=False)  # профиль неполный
    await add_event(2001, REGISTRATION_STARTED, timedelta(minutes=40))
    # отмена
    await add_user(2002, face=False, birth=False)
    await add_event(2002, REGISTRATION_STARTED, timedelta(minutes=40))
    await add_event(2002, PROFILE_COMPLETED, timedelta(minutes=30))

    await run_sweep(bot)
    assert push_text("push_e2_1") in bot.texts_for(2001)
    assert not bot.texts_for(2002), "E2 отменяется profile_completed"


async def test_e3_couple_partner_fires_and_cancel():
    """E3. Начал совместимость → не ввёл партнёра.

    Пуш 1 — через 30 минут: «Для анализа пары не хватает данных второго человека.»
    Пуш 2 — через 24 часа: «Добавь данные партнёра…»

    Отмена: couple_partner_completed после couple_partner_started.
    """
    bot = MockBot()
    await add_user(3001)
    await add_event(3001, COUPLE_PARTNER_STARTED, timedelta(minutes=40))
    await add_user(3002)
    await add_event(3002, COUPLE_PARTNER_STARTED, timedelta(minutes=40))
    await add_event(3002, COUPLE_PARTNER_COMPLETED, timedelta(minutes=35))

    await run_sweep(bot)
    assert push_text("push_e3_1") in bot.texts_for(3001)
    assert not bot.texts_for(3002), "E3 отменяется couple_partner_completed"


async def test_e4_demo_not_bought_three_pushes_and_cancel():
    """E4. Получил демо → не купил (3 пуши, по каждому report_type отдельно).

    Пуш 1 — 20 мин: «Ты увидел только часть своего анализа.»
    Пуш 2 — 12 ч:   «Самые важные выводы остались закрыты.»
    Пуш 3 — 48 ч:   «Полный разбор всё ещё доступен.»

    Отмена: payment_initiated ИЛИ purchase_completed для того же report_type
    после demo_shown (переход к оплате/покупке).
    event_key: e4:{report_type}:N.
    """
    bot = MockBot()
    # три демо на трёх типах, возраст 49ч → все три пуша
    await add_user(4001)
    for rt in ("self", "money", "couple"):
        await add_event(4001, DEMO_SHOWN, timedelta(hours=49), report_type=rt)
    # отмена: после demo — payment_initiated для того же report_type
    await add_user(4002)
    await add_event(4002, DEMO_SHOWN, timedelta(hours=49), report_type="self")
    await add_event(4002, PAYMENT_INITIATED, timedelta(hours=1),
                    report_type="self", plan="base", payment_id="pay4002")

    await run_sweep(bot)
    t = bot.texts_for(4001)
    assert t.count(push_text("push_e4_1")) == 3, "E4:1 для каждого report_type"
    assert t.count(push_text("push_e4_2")) == 3
    assert t.count(push_text("push_e4_3")) == 3
    assert not bot.texts_for(4002), "E4 отменяется payment_initiated"

    # event_key содержит report_type
    keys = await logged_keys(4001)
    assert "e4:self:1" in keys and "e4:money:3" in keys and "e4:couple:2" in keys


async def test_e5_payment_not_completed_three_pushes_and_cancel():
    """E5. Нажал оплатить → не оплатил (по самому свежему pending-платежу).

    Пуш 1 — 15 мин: «Оплата не завершена. Твой анализ уже готов.»
    Пуш 2 — 3 ч:    «Остался один шаг до полного доступа.»
    Пуш 3 — 24 ч:   «Заверши оплату и открой свой разбор.»

    Отмена: платеж стал succeeded (sweep берёт только pending).
    event_key: e5:{yookassa_id}:N.
    """
    bot = MockBot()
    await add_user(5001)
    await add_payment(5001, "pay5001", age=timedelta(hours=25))  # все 3 пуши
    # отмена: succeeded
    await add_user(5002)
    await add_payment(5002, "pay5002", status="succeeded", age=timedelta(hours=25))

    await run_sweep(bot)
    t = bot.texts_for(5001)
    assert push_text("push_e5_1") in t
    assert push_text("push_e5_2") in t
    assert push_text("push_e5_3") in t
    assert not bot.texts_for(5002), "E5 не срабатывает для succeeded"
    assert "e5:pay5001:3" in await logged_keys(5001)


async def test_e5_only_latest_pending_per_user():
    """Если у пользователя несколько pending-платежей, пуш идёт только по самому свежему
    (чтобы не спамить за каждую брошенную попытку)."""
    bot = MockBot()
    await add_user(5003)
    await add_payment(5003, "old", age=timedelta(hours=25))
    await add_payment(5003, "new", age=timedelta(minutes=20))  # свежее
    await run_sweep(bot)
    # только новый получит e5:1, старый не должен получить свои e5:2/e5:3
    keys = await logged_keys(5003)
    assert "e5:new:1" in keys
    assert not any(k.startswith("e5:old:") for k in keys), "старый pending не должен пушиться"


async def test_e6_cross_sell_fires_and_cancel():
    """E6. Купил один продукт → не купил остальные (один пуш через 24ч).

    Текст зависит от купленного report_type:
      self   → «Теперь узнай, как твои особенности влияют на деньги и отношения.»
      money  → «Теперь узнай, какие отношения усиливают или ослабляют твой путь.»
      couple → «Теперь узнай, почему именно такие люди появляются в твоей жизни.»

    Отмена: куплен другой продукт (другой report_type).
    event_key: e6:{report_type}.
    """
    bot = MockBot()
    # купил только self 25ч назад → ждём e6:self
    await add_user(6001)
    await add_event(6001, PURCHASE_COMPLETED, timedelta(hours=25),
                    report_type="self", plan="base", payment_id="p6a")
    # купил self + money → e6 не срабатывает ни для одного
    await add_user(6002)
    await add_event(6002, PURCHASE_COMPLETED, timedelta(hours=25),
                    report_type="self", plan="base", payment_id="p6b1")
    await add_event(6002, PURCHASE_COMPLETED, timedelta(hours=20),
                    report_type="money", plan="base", payment_id="p6b2")

    await run_sweep(bot)
    assert push_text("push_e6_self") in bot.texts_for(6001)
    e6_texts = {push_text(f"push_e6_{r}") for r in ("self", "money", "couple")}
    assert not any(t in e6_texts for t in bot.texts_for(6002)), "E6 отменяется вторым продуктом"
    assert "e6:self" in await logged_keys(6001)


async def test_e7_upgrade_to_premium_fires_and_cancel():
    """E7. Купил базовый/расширенный → не купил премиум.

    Пуш 1 — 2 ч:  «Ты открыл только часть своего анализа.»
    Пуш 2 — 24 ч: «Самые глубокие выводы доступны в Премиум.»

    Отмена: для того же report_type куплен plan='full'.
    event_key: e7:{report_type}:N.
    """
    bot = MockBot()
    await add_user(7001)
    await add_event(7001, PURCHASE_COMPLETED, timedelta(hours=3),
                    report_type="couple", plan="base", payment_id="p7a")
    # отмена: затем куплен full
    await add_user(7002)
    await add_event(7002, PURCHASE_COMPLETED, timedelta(hours=3),
                    report_type="couple", plan="base", payment_id="p7b1")
    await add_event(7002, PURCHASE_COMPLETED, timedelta(hours=2),
                    report_type="couple", plan="full", payment_id="p7b2")

    await run_sweep(bot)
    assert push_text("push_e7_1") in bot.texts_for(7001)
    assert not bot.texts_for(7002), "E7 отменяется покупкой full"
    assert "e7:couple:1" in await logged_keys(7001)


async def test_e8_reactivation_fires_and_skip_without_report():
    """E8. Давно не заходил.

    Пуш 1 — 7 дней:  «Твои разборы всё ещё ждут тебя.»
    Пуш 2 — 30 дней: «Возможно, сейчас именно то время…»

    Условие: у пользователя есть хоть один отчёт (blocks_json иначе пуш неосмыслен).
    Отмена: любая активность обновляет last_activity_at (в тесте просто не трогаем).
    """
    bot = MockBot()
    # неактивен 8 дней, есть отчёт → e8:1
    await add_user(8001, last_activity=datetime.now(timezone.utc) - timedelta(days=8),
                   reports=("self",))
    # неактивен 31 день, есть отчёт → e8:1 и e8:2
    await add_user(8002, last_activity=datetime.now(timezone.utc) - timedelta(days=31),
                   reports=("money",))
    # неактивен 8 дней, НО отчётов нет → пуша быть не должно
    await add_user(8003, last_activity=datetime.now(timezone.utc) - timedelta(days=8))

    await run_sweep(bot)
    assert push_text("push_e8_1") in bot.texts_for(8001)
    assert push_text("push_e8_2") in bot.texts_for(8002)
    assert not bot.texts_for(8003), "E8 не срабатывает без отчётов"


# ═════════════════════════════════════════════════════════════════════════════
# ТЕСТЫ: КРАЕВЫЕ СЛУЧАИ
# ═════════════════════════════════════════════════════════════════════════════

async def test_blocked_users_are_skipped():
    """Заблокировавшие бот пользователи (is_blocked=True) исключаются из всех sweep-запросов."""
    bot = MockBot()
    await add_user(9001, blocked=True)
    await add_event(9001, ENTERED_MENU, timedelta(minutes=20))
    await run_sweep(bot)
    assert not bot.texts_for(9001), "заблокированный пользователь не получает пуши"


async def test_idempotency_no_resends():
    """Повторный sweep не дублирует уже отправленные пуши (notification_log)."""
    bot = MockBot()
    await add_user(9101)
    await add_event(9101, ENTERED_MENU, timedelta(minutes=20))
    await run_sweep(bot)
    n1 = len(bot.sent)
    await run_sweep(bot)  # второй прогон
    n2 = len(bot.sent)
    assert n1 == n2, f"повторный sweep не должен дублировать ({n1} → {n2})"


async def test_idempotency_via_log_keys():
    """После отправки event_key появляется в notification_log и блокирует повтор."""
    await add_user(9102)
    await add_event(9102, ENTERED_MENU, timedelta(minutes=20))
    bot = MockBot()
    await run_sweep(bot)
    assert "e1:1" in await logged_keys(9102)


# ═════════════════════════════════════════════════════════════════════════════
# ТЕСТЫ: ВОРОНКА (СТАДИИ)
# ═════════════════════════════════════════════════════════════════════════════

async def test_funnel_stage_per_scenario():
    """get_user_funnel корректно вычисляет стадию для каждого сценария.

    Порядок приоритета стадий:
      blocked → inactive(≥7д) → paying → bought → demo_seen
      → couple_pending → menu_idle → registering → unknown_activity → new
    """
    # new: только создан, без событий, есть last_activity
    await add_user(1, name=None, face=False, birth=False,
                   last_activity=datetime.now(timezone.utc))
    # registering: reg_started, профиль не полный
    await add_user(2, face=False, birth=False)
    await add_event(2, REGISTRATION_STARTED, timedelta(minutes=5))
    # menu_idle: полный профиль + entered_menu, без демо
    await add_user(3)
    await add_event(3, ENTERED_MENU, timedelta(hours=1))
    # couple_pending: couple_started без couple_done
    await add_user(4)
    await add_event(4, COUPLE_PARTNER_STARTED, timedelta(hours=1))
    # demo_seen
    await add_user(5)
    await add_event(5, DEMO_SHOWN, timedelta(hours=1), report_type="self")
    # paying: есть pending
    await add_user(6)
    await add_payment(6, "p6", status="pending", age=timedelta(minutes=10))
    # bought
    await add_user(7)
    await add_event(7, PURCHASE_COMPLETED, timedelta(hours=1),
                    report_type="self", plan="base", payment_id="p7")
    # inactive: активность 10 дней назад + есть отчёт
    await add_user(8, last_activity=datetime.now(timezone.utc) - timedelta(days=10),
                   reports=("self",))
    # blocked
    await add_user(9, blocked=True)

    expected = {
        1: "new", 2: "registering", 3: "menu_idle", 4: "couple_pending",
        5: "demo_seen", 6: "paying", 7: "bought", 8: "inactive", 9: "blocked",
    }
    for tg, stage in expected.items():
        data = await get_user_funnel(tg)
        assert data["stage"] == stage, (
            f"tg={tg}: ожидал {stage}, получил {data['stage']}"
        )


async def test_funnel_inactive_takes_precedence_over_bought():
    """inactive имеет приоритет над bought: покупатель, ушедший ≥7 дней,
    тоже цель E8 (реактивация)."""
    await add_user(10, last_activity=datetime.now(timezone.utc) - timedelta(days=10),
                   reports=("self",))
    await add_event(10, PURCHASE_COMPLETED, timedelta(days=12),
                    report_type="self", plan="base", payment_id="p10")
    data = await get_user_funnel(10)
    assert data["stage"] == "inactive"
    # но покупка всё равно видна в карточке
    assert data["bought"] == {"self": "base"}


async def test_funnel_highest_plan_per_report():
    """В карточке купленного показывается высший план на каждый report_type
    (base → extended → full)."""
    await add_user(11)
    await add_event(11, PURCHASE_COMPLETED, timedelta(days=2),
                    report_type="self", plan="base", payment_id="p11a")
    await add_event(11, PURCHASE_COMPLETED, timedelta(days=1),
                    report_type="self", plan="full", payment_id="p11b")
    data = await get_user_funnel(11)
    assert data["bought"] == {"self": "full"}


async def test_funnel_distribution_counts():
    """get_funnel_distribution возвращает подсчёт по стадиям с процентами."""
    # 2 registering + 1 bought
    for i in range(2):
        await add_user(20 + i, face=False, birth=False)
        await add_event(20 + i, REGISTRATION_STARTED, timedelta(minutes=5))
    await add_user(22)
    await add_event(22, PURCHASE_COMPLETED, timedelta(hours=1),
                    report_type="self", plan="base", payment_id="p22")

    dist = dict(await get_funnel_distribution())
    assert dist.get("registering") == 2
    assert dist.get("bought") == 1
    assert sum(dist.values()) == 3


async def test_funnel_card_contains_sent_pushes():
    """Карточка пользователя показывает уже отправленные ему пуши."""
    await add_user(30)
    await add_event(30, DEMO_SHOWN, timedelta(hours=1), report_type="self")
    bot = MockBot()
    # отправим e4:self:1, сдвинув время
    await add_event(30, DEMO_SHOWN, timedelta(hours=1), report_type="self")  # лишний — не важно
    # проще: запишем вручную в notification_log
    async with async_session() as s:
        s.add(NotificationLog(telegram_id=30, event_key="e4:self:1"))
        await s.commit()
    data = await get_user_funnel(30)
    assert "e4:self:1" in data["sent"]


# ═════════════════════════════════════════════════════════════════════════════
# RUNNER
# ═════════════════════════════════════════════════════════════════════════════

async def _run_all():
    await init_db()
    tests = sorted(
        (name, fn) for name, fn in sorted(globals().items())
        if name.startswith("test_") and callable(fn)
    )
    passed, failed = 0, 0
    for name, fn in tests:
        await clean()
        try:
            await fn()
            print(f"  ✓ {name}")
            passed += 1
        except AssertionError as e:
            print(f"  ✗ {name}: {e}")
            failed += 1
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ {name}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{'=' * 60}")
    print(f"Итого: {passed} прошёл, {failed} провален, {passed + failed} всего")
    await engine.dispose()
    try:
        os.unlink(_TMPDB)
    except OSError:
        pass
    return failed


if __name__ == "__main__":
    rc = asyncio.run(_run_all())
    sys.exit(1 if rc else 0)
