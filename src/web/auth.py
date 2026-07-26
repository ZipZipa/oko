"""Проверка подписи Telegram WebApp initData.

Клиент мини-аппа присылает строку `Telegram.WebApp.initData` — query-string,
подписанную ботом. Проверяем HMAC по алгоритму из документации Telegram:
секрет = HMAC_SHA256(key="WebAppData", msg=bot_token), затем этим секретом
подписывается data_check_string (все поля кроме hash, отсортированы, \\n).
"""
import hashlib
import hmac
import json
import logging
import time
from urllib.parse import parse_qsl

log = logging.getLogger(__name__)

# initData живёт сутки — дольше принимать нет смысла, это защита от реплея
MAX_AGE_SECONDS = 24 * 60 * 60


class InitDataError(Exception):
    """initData отсутствует, просрочен или подпись не сошлась."""


def parse_init_data(init_data: str, bot_token: str,
                    max_age: int = MAX_AGE_SECONDS) -> dict:
    """Проверяет подпись и возвращает распарсенные поля initData.

    В результате поле `user` — уже словарь (Telegram присылает его как JSON-строку).
    Бросает InitDataError, если что-то не так.
    """
    if not init_data:
        raise InitDataError("initData пустой")
    if not bot_token:
        raise InitDataError("BOT_TOKEN не задан — нечем проверять подпись")

    pairs = parse_qsl(init_data, keep_blank_values=True)
    data = dict(pairs)

    received_hash = data.pop("hash", None)
    if not received_hash:
        raise InitDataError("в initData нет hash")

    data_check_string = "\n".join(
        f"{k}={v}" for k, v in sorted(data.items())
    )
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_hash, received_hash):
        raise InitDataError("подпись initData не сошлась")

    auth_date = data.get("auth_date")
    if not (auth_date or "").isdigit():
        raise InitDataError("в initData нет auth_date")
    age = time.time() - int(auth_date)
    if age > max_age:
        raise InitDataError(f"initData просрочен ({int(age)}s)")

    raw_user = data.get("user")
    if not raw_user:
        raise InitDataError("в initData нет user")
    try:
        data["user"] = json.loads(raw_user)
    except json.JSONDecodeError as e:
        raise InitDataError(f"user в initData не парсится: {e}") from e

    if not isinstance(data["user"].get("id"), int):
        raise InitDataError("в user нет числового id")

    return data


def telegram_id_from_init_data(init_data: str, bot_token: str) -> int:
    """Короткий путь: проверить подпись и достать telegram_id."""
    return parse_init_data(init_data, bot_token)["user"]["id"]
