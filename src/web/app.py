"""aiohttp-приложение мини-аппа «Спросить ОКО».

Роуты:
  GET  /            — страница чата
  GET  /static/*    — статика
  GET  /health      — проверка живости для systemd/nginx
  POST /api/state   — состояние чата: история, остаток лимита, что куплено
  POST /api/chat    — вопрос → ответ модели потоком (SSE)
  POST /api/reset   — очистить переписку
  POST /api/upsell  — прислать в бот сообщение с пакетами и закрыть мини-апп

Авторизация — во всех /api/* по заголовку X-Telegram-Init-Data
(подписанный Telegram initData мини-аппа).
"""
import json
import logging
from pathlib import Path

from aiohttp import web
from sqlalchemy import select

from src.bot.config import BOT_TOKEN, WEB_HOST, WEB_PORT
from src.bot.db import async_session, User
from src.bot.notifications.events import (
    log_event, log_event_once,
    CHAT_OPENED, CHAT_MESSAGE_SENT, CHAT_LIMIT_REACHED,
)
from src.web import chat as chat_service
from src.web.auth import InitDataError, parse_init_data
from src.web.context import max_plan, owned_reports

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
INDEX_FILE = STATIC_DIR / "index.html"

USER_KEY = web.AppKey("user", User)
BOT_KEY = web.AppKey("bot", object)


# ─── Авторизация ────────────────────────────────────────────────────────────────

@web.middleware
async def auth_middleware(request: web.Request, handler):
    """Для /api/* проверяет initData и кладёт пользователя в request."""
    if not request.path.startswith("/api/"):
        return await handler(request)

    init_data = request.headers.get("X-Telegram-Init-Data", "")
    try:
        parsed = parse_init_data(init_data, BOT_TOKEN)
    except InitDataError as e:
        log.warning("auth: отклонён запрос на %s — %s", request.path, e)
        raise web.HTTPUnauthorized(
            text=json.dumps({"error": "unauthorized"}),
            content_type="application/json",
        )

    telegram_id = parsed["user"]["id"]
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()

    if user is None:
        raise web.HTTPForbidden(
            text=json.dumps({"error": "no_profile"}),
            content_type="application/json",
        )

    request[USER_KEY] = user
    return await handler(request)


# ─── Роуты ──────────────────────────────────────────────────────────────────────

async def index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(INDEX_FILE, headers={"Cache-Control": "no-cache"})


async def health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


def _profile_ready(user: User) -> bool:
    return bool(user.name and user.birth_date and user.face_json)


async def api_state(request: web.Request) -> web.Response:
    user: User = request[USER_KEY]

    limit = chat_service.question_limit(user)
    used = await chat_service.questions_used(user.telegram_id)
    history = await chat_service.load_history(user.telegram_id, limit=200)

    await log_event_once(user.telegram_id, CHAT_OPENED)

    return web.json_response({
        "name": user.name or "",
        "profileReady": _profile_ready(user),
        "plan": max_plan(user),
        "ownedReports": owned_reports(user),
        "limit": limit,
        "used": used,
        "left": max(limit - used, 0),
        "messages": history,
        "suggestions": _suggestions(user),
    })


def _suggestions(user: User) -> list[str]:
    """Стартовые подсказки — под то, что у человека уже разобрано."""
    owned = set(owned_reports(user))
    items = ["Что во мне считывается людьми в первую очередь?"]
    if "money" in owned:
        items.append("Что мешает мне зарабатывать больше?")
    else:
        items.append("Как мой характер влияет на отношение к деньгам?")
    if "couple" in owned:
        items.append("В чём главный риск в наших отношениях?")
    else:
        items.append("Какие люди меня притягивают и почему?")
    items.append("Какой сейчас период по числам и что в нём делать?")
    return items


async def api_chat(request: web.Request) -> web.StreamResponse:
    """Вопрос → ответ потоком в формате Server-Sent Events."""
    user: User = request[USER_KEY]

    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(
            text=json.dumps({"error": "bad_json"}), content_type="application/json"
        )

    try:
        question = chat_service.normalize_question(body.get("question"))
    except chat_service.EmptyQuestion as e:
        raise web.HTTPBadRequest(
            text=json.dumps({"error": "bad_question", "detail": str(e)}),
            content_type="application/json",
        )

    limit = chat_service.question_limit(user)
    used = await chat_service.questions_used(user.telegram_id)
    if used >= limit:
        await log_event_once(user.telegram_id, CHAT_LIMIT_REACHED)
        raise web.HTTPPaymentRequired(
            text=json.dumps({"error": "limit_reached", "limit": limit, "used": used}),
            content_type="application/json",
        )

    response = web.StreamResponse(
        headers={
            "Content-Type": "text/event-stream; charset=utf-8",
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",   # nginx не должен буферизовать поток
        }
    )
    await response.prepare(request)

    async def send(event: str, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False)
        await response.write(f"event: {event}\ndata: {data}\n\n".encode())

    try:
        async for piece in chat_service.answer(user, question):
            await send("token", {"text": piece})
    except chat_service.ChatLimitReached:
        # Гонка: лимит закончился между проверкой выше и списанием
        await log_event_once(user.telegram_id, CHAT_LIMIT_REACHED)
        await send("limit", {"limit": limit})
        await response.write_eof()
        return response
    except ConnectionResetError:
        log.info("chat: клиент отключился tg=%s", user.telegram_id)
        return response
    except Exception:
        log.error("chat: ошибка генерации ответа tg=%s", user.telegram_id, exc_info=True)
        await send("error", {"message": "Не получилось ответить. Попробуй ещё раз."})
        await response.write_eof()
        return response

    await log_event(user.telegram_id, CHAT_MESSAGE_SENT)
    left = max(limit - await chat_service.questions_used(user.telegram_id), 0)
    if left == 0:
        await log_event_once(user.telegram_id, CHAT_LIMIT_REACHED)
    await send("done", {"left": left, "limit": limit})
    await response.write_eof()
    return response


async def api_reset(request: web.Request) -> web.Response:
    user: User = request[USER_KEY]
    await chat_service.clear_history(user.telegram_id)
    return web.json_response({"ok": True})


_UPSELL_TEXT = (
    "<b>Спросить ОКО</b>\n\n"
    "Бесплатные вопросы закончились. Полный разбор открывает больше вопросов "
    "и даёт чату весь материал по тебе — выбери направление."
)


async def api_upsell(request: web.Request) -> web.Response:
    """Присылает в чат бота сообщение с разделами — мини-апп после этого закрывается."""
    user: User = request[USER_KEY]
    bot = request.app[BOT_KEY]

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Портрет личности", callback_data="show_packages_self")],
        [InlineKeyboardButton(text="Денежная карта", callback_data="show_packages_money")],
        [InlineKeyboardButton(text="Совместимость пары", callback_data="show_packages_couple")],
    ])
    try:
        await bot.send_message(
            chat_id=user.telegram_id,
            text=_UPSELL_TEXT,
            parse_mode="HTML",
            reply_markup=markup,
        )
    except Exception:
        log.error("upsell: не удалось отправить сообщение tg=%s",
                  user.telegram_id, exc_info=True)
        return web.json_response({"ok": False}, status=502)

    return web.json_response({"ok": True})


# ─── Сборка приложения ──────────────────────────────────────────────────────────

async def _init_db(app: web.Application) -> None:
    # Внутри startup, а не до run_app: async-движок привязывается к тому циклу,
    # в котором его впервые использовали.
    from src.bot.db import init_db
    await init_db()


async def _close_bot(app: web.Application) -> None:
    await app[BOT_KEY].session.close()


async def _dispose_engine(app: web.Application) -> None:
    from src.bot.db.session import engine
    await engine.dispose()


def create_app() -> web.Application:
    from aiogram import Bot
    from src.bot.retry import RetryRequestMiddleware

    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не задан — мини-апп не сможет проверить initData")

    app = web.Application(middlewares=[auth_middleware])

    bot = Bot(token=BOT_TOKEN)
    bot.session.middleware(RetryRequestMiddleware())
    app[BOT_KEY] = bot

    app.on_startup.append(_init_db)
    app.on_cleanup.append(_close_bot)
    app.on_cleanup.append(_dispose_engine)

    app.router.add_get("/", index)
    app.router.add_get("/health", health)
    app.router.add_post("/api/state", api_state)
    app.router.add_post("/api/chat", api_chat)
    app.router.add_post("/api/reset", api_reset)
    app.router.add_post("/api/upsell", api_upsell)
    app.router.add_static("/static/", STATIC_DIR, name="static")

    return app


def run() -> None:
    app = create_app()
    log.info("Мини-апп «Спросить ОКО» слушает %s:%s", WEB_HOST, WEB_PORT)
    web.run_app(app, host=WEB_HOST, port=WEB_PORT, print=None)
