"""
Универсальная обёртка над OpenAI‑совместимым API (Polza).
Валидатор передаётся как функция — клиент работает для всех типов отчётов.
"""
import json
import logging
import os
import time
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv
from openai import OpenAI

# Загружаем .env из корня проекта
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://polza.ai/api/v1"
DEFAULT_MODEL = "claude-sonnet-4-5"
DEFAULT_MAX_TOKENS = 8000
DEFAULT_TEMPERATURE = 0.7


def _get_client() -> OpenAI:
    api_key = os.environ.get("AI_API_KEY")
    if not api_key:
        raise RuntimeError("AI_API_KEY environment variable not set")
    base_url = os.environ.get("AI_BASE_URL", DEFAULT_BASE_URL)
    return OpenAI(base_url=base_url, api_key=api_key)


def call_claude(system: str, messages: list[dict], model: str | None = None,
                max_tokens: int | None = None, temperature: float | None = None,
                telegram_id: int | None = None) -> str:
    """Вызов LLM. telegram_id — опциональный контекст для логирования."""
    _ctx = f"tg={telegram_id} " if telegram_id else ""
    client = _get_client()
    model = model or os.environ.get("AI_MODEL", DEFAULT_MODEL)
    max_tokens = max_tokens or int(os.environ.get("AI_MAX_TOKENS", DEFAULT_MAX_TOKENS))
    temperature = temperature if temperature is not None else float(os.environ.get("AI_TEMPERATURE", DEFAULT_TEMPERATURE))

    log.info("%sLLM call: model=%s, max_tokens=%s, messages=%d",
             _ctx, model, max_tokens, len(messages))

    # Собираем сообщения в формат OpenAI Chat
    openai_messages: list[dict] = [{"role": "system", "content": system}]
    openai_messages.extend(messages)

    t0 = time.monotonic()
    try:
        response = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=openai_messages,
        )
    except Exception as e:
        # Сетевые ошибки / 429 / 5xx от API — логируем с контекстом, чтобы
        # в логе было видно какого пользователя затронул сбой.
        log.error("%sLLM call failed: %s", _ctx, e, exc_info=True)
        raise

    elapsed = time.monotonic() - t0
    content = response.choices[0].message.content
    usage = getattr(response, "usage", None)
    if usage:
        log.info("%sLLM response: %.2fs, prompt_tokens=%s, completion_tokens=%s",
                 _ctx, elapsed,
                 getattr(usage, "prompt_tokens", "?"),
                 getattr(usage, "completion_tokens", "?"))
    else:
        log.info("%sLLM response: %.2fs (usage missing)", _ctx, elapsed)
    return content


def parse_blocks_json(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    return json.loads(text)


def generate_blocks(system: str, messages: list[dict],
                    validate_fn: Callable[[dict], list[str]],
                    model: str | None = None,
                    max_retries: int = 2,
                    telegram_id: int | None = None) -> dict:
    _ctx = f"tg={telegram_id} " if telegram_id else ""
    last_error = None
    current_messages = messages

    for attempt in range(max_retries + 1):
        log.info("%sLLM generate_blocks: попытка %d/%d", _ctx, attempt + 1, max_retries + 1)
        try:
            raw = call_claude(system, current_messages, model=model, telegram_id=telegram_id)
        except Exception:
            # Сетевая ошибка уже залогирована в call_claude. Пробрасываем выше —
            # ретраи по сетевым ошибкам здесь не делаем (это задача HTTP-клиента).
            raise

        try:
            blocks = parse_blocks_json(raw)
        except json.JSONDecodeError as e:
            last_error = f"Invalid JSON: {e}"
            log.warning("%sПопытка %d: ошибка парсинга JSON — %s", _ctx, attempt + 1, e)
            tmp_path = "/tmp/llm_raw_response.txt"
            try:
                with open(tmp_path, "w", encoding="utf-8") as f:
                    f.write(raw)
                log.info("%sСырой ответ LLM сохранён в %s", _ctx, tmp_path)
            except OSError as write_err:
                log.warning("%sНе удалось сохранить сырой ответ: %s", _ctx, write_err)
            current_messages = _build_retry_messages(messages, raw, last_error)
            continue

        errors = validate_fn(blocks)
        if not errors:
            log.info("%sLLM generate_blocks: успех на попытке %d", _ctx, attempt + 1)
            return blocks

        last_error = "Validation errors:\n  - " + "\n  - ".join(errors)
        log.warning("%sПопытка %d: ошибки валидации:\n%s", _ctx, attempt + 1, last_error)
        current_messages = _build_retry_messages(messages, raw, last_error)

    log.error("%sgenerate_blocks: все %d попытки исчерпаны. Последняя ошибка: %s",
              _ctx, max_retries + 1, last_error)
    raise RuntimeError(f"Failed after {max_retries + 1} attempts. Last error:\n{last_error}")


def _build_retry_messages(original: list[dict], bad_response: str, error: str) -> list[dict]:
    return original + [
        {"role": "assistant", "content": bad_response},
        {"role": "user", "content": (
            f"Твой ответ не прошёл проверку:\n\n{error}\n\n"
            f"Исправь и верни ПОЛНЫЙ JSON по той же схеме. "
            f"Только JSON, без обёрток и комментариев."
        )},
    ]