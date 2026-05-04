"""
Универсальная обёртка над OpenAI‑совместимым API (Polza).
Валидатор передаётся как функция — клиент работает для всех типов отчётов.
"""
import json
import os
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv
from openai import OpenAI

# Загружаем .env из корня проекта
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")


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
                max_tokens: int | None = None, temperature: float | None = None) -> str:
    client = _get_client()
    model = model or os.environ.get("AI_MODEL", DEFAULT_MODEL)
    max_tokens = max_tokens or int(os.environ.get("AI_MAX_TOKENS", DEFAULT_MAX_TOKENS))
    temperature = temperature if temperature is not None else float(os.environ.get("AI_TEMPERATURE", DEFAULT_TEMPERATURE))

    # Собираем сообщения в формат OpenAI Chat
    openai_messages: list[dict] = [{"role": "system", "content": system}]
    openai_messages.extend(messages)

    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=openai_messages,
    )
    return response.choices[0].message.content


def parse_blocks_json(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    return json.loads(text)


def generate_blocks(system: str, messages: list[dict],
                    validate_fn: Callable[[dict], list[str]],
                    model: str | None = None,
                    max_retries: int = 2) -> dict:
    last_error = None
    current_messages = messages

    for attempt in range(max_retries + 1):
        raw = call_claude(system, current_messages, model=model)

        try:
            blocks = parse_blocks_json(raw)
        except json.JSONDecodeError as e:
            last_error = f"Invalid JSON: {e}"
            with open("/tmp/llm_raw_response.txt", "w", encoding="utf-8") as f:
                f.write(raw)
            current_messages = _build_retry_messages(messages, raw, last_error)
            continue

        errors = validate_fn(blocks)
        if not errors:
            return blocks

        last_error = "Validation errors:\n  - " + "\n  - ".join(errors)
        current_messages = _build_retry_messages(messages, raw, last_error)

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