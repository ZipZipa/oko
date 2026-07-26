"""Логика чата «Спросить ОКО»: история, лимиты, промпт, стриминг ответа."""
import logging
from typing import AsyncIterator

from sqlalchemy import select, delete, update

from src.bot.config import (
    CHAT_LIMITS, CHAT_HISTORY_MESSAGES, CHAT_MAX_QUESTION_CHARS,
)
from src.bot.db import async_session, ChatMessage, User
from src.core.llm_client import astream_chat
from src.web.context import build_context, max_plan, owned_reports

log = logging.getLogger(__name__)


SYSTEM_PROMPT = """Ты — ОКО, собеседник, который разбирает человека по его данным.

О ЧЁМ ГОВОРИШЬ:
Тебе передан профиль пользователя (нумерология, матрица судьбы, черты лица,
физиогномика, ладони) и тексты его отчётов. Отвечаешь на вопросы про него:
характер, отношения, деньги, работа, состояние, решения.

ТОН:
- Холодный, точный, без лести и без утешений
- Прямые наблюдения, не эзотерические штампы и не гороскоп
- Обращение на "ты". Имя не используй — только второе лицо
- Без эмоджи

ПРАВИЛА:
1. Опирайся на переданные данные. Каждый вывод должен иметь опору в профиле
   или в отчёте — называй её: "по матрице …", "по чертам лица …", "в отчёте …".
2. Числа уже посчитаны. Не пересчитывай, не показывай формулы.
3. Не выдумывай данные, которых нет. Если ладони не загружены или отчёт не
   куплен — скажи прямо, что этих данных нет, и ответь по тому, что есть.
4. Если системы противоречат друг другу — назови противоречие, не сглаживай.
5. Отвечай коротко: 2–5 абзацев. На простой вопрос — несколько предложений.
6. Не давай медицинских, юридических и финансовых предписаний. Это разбор
   личности, а не диагноз и не инвестиционный совет.
7. Если вопрос не про человека и не про его разбор — коротко верни разговор
   к теме анализа.
8. Обычный текст без разметки. Списки — через "— " в начале строки.
9. Только русский язык.
"""


class ChatLimitReached(Exception):
    """У пользователя закончились доступные вопросы."""


class EmptyQuestion(Exception):
    """Пустой или слишком длинный вопрос."""


def question_limit(user: User) -> int:
    """Сколько всего вопросов доступно пользователю по его максимальному пакету."""
    return CHAT_LIMITS.get(max_plan(user), CHAT_LIMITS["demo"])


async def questions_used(telegram_id: int) -> int:
    """Сколько вопросов уже задано.

    Счётчик лежит в users.chat_questions_used, а не считается по chat_messages:
    очистка переписки не должна возвращать исчерпанный лимит.
    """
    async with async_session() as session:
        result = await session.execute(
            select(User.chat_questions_used).where(User.telegram_id == telegram_id)
        )
        return int(result.scalar() or 0)


async def _consume_question(telegram_id: int, limit: int) -> int:
    """Атомарно списывает один вопрос из лимита. Возвращает новое значение.

    Инкремент делаем одним UPDATE с условием по лимиту — иначе два параллельных
    запроса из одного мини-аппа могли бы проскочить оба.
    """
    async with async_session() as session:
        result = await session.execute(
            update(User)
            .where(
                User.telegram_id == telegram_id,
                User.chat_questions_used < limit,
            )
            .values(chat_questions_used=User.chat_questions_used + 1)
        )
        if result.rowcount == 0:
            await session.rollback()
            raise ChatLimitReached(f"лимит {limit} исчерпан")
        await session.commit()

        used = await session.execute(
            select(User.chat_questions_used).where(User.telegram_id == telegram_id)
        )
        return int(used.scalar() or limit)


async def load_history(telegram_id: int, limit: int = CHAT_HISTORY_MESSAGES) -> list[dict]:
    """Последние сообщения диалога в хронологическом порядке."""
    async with async_session() as session:
        result = await session.execute(
            select(ChatMessage)
            .where(ChatMessage.telegram_id == telegram_id)
            .order_by(ChatMessage.id.desc())
            .limit(limit)
        )
        rows = list(result.scalars())
    rows.reverse()
    return [{"role": r.role, "content": r.content} for r in rows]


async def save_message(telegram_id: int, role: str, content: str) -> None:
    async with async_session() as session:
        session.add(ChatMessage(telegram_id=telegram_id, role=role, content=content))
        await session.commit()


def normalize_question(raw: str | None) -> str:
    text = (raw or "").strip()
    if not text:
        raise EmptyQuestion("пустой вопрос")
    if len(text) > CHAT_MAX_QUESTION_CHARS:
        raise EmptyQuestion(f"вопрос длиннее {CHAT_MAX_QUESTION_CHARS} символов")
    return text


def build_system_prompt(user: User) -> str:
    """Системный промпт + контекст конкретного пользователя."""
    context = build_context(user)
    owned = owned_reports(user)
    owned_line = (
        "Куплены отчёты: " + ", ".join(owned)
        if owned else
        "Платных отчётов пока нет — доступен только демо-разбор."
    )
    return f"{SYSTEM_PROMPT}\n{owned_line}\n\n─── ДАННЫЕ ПОЛЬЗОВАТЕЛЯ ───\n{context}"


async def answer(user: User, question: str) -> AsyncIterator[str]:
    """Сохраняет вопрос, стримит ответ модели и сохраняет его целиком.

    Бросает ChatLimitReached, если лимит вопросов исчерпан — до записи вопроса
    в историю и до вызова LLM.
    """
    limit = question_limit(user)
    await _consume_question(user.telegram_id, limit)

    history = await load_history(user.telegram_id)
    await save_message(user.telegram_id, "user", question)

    system = build_system_prompt(user)
    messages = history + [{"role": "user", "content": question}]

    parts: list[str] = []
    try:
        async for piece in astream_chat(system, messages, telegram_id=user.telegram_id):
            parts.append(piece)
            yield piece
    finally:
        # Сохраняем даже частичный ответ: пользователь его уже увидел,
        # и в следующем запросе история должна совпадать с картинкой на экране.
        if parts:
            await save_message(user.telegram_id, "assistant", "".join(parts))
        else:
            log.warning("chat: пустой ответ модели tg=%s", user.telegram_id)


async def clear_history(telegram_id: int) -> None:
    """Удаляет переписку (лимит вопросов при этом не обнуляется — он общий)."""
    async with async_session() as session:
        await session.execute(
            delete(ChatMessage).where(ChatMessage.telegram_id == telegram_id)
        )
        await session.commit()
