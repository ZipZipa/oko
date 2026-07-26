import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///oko_bot.db")
YOOKASSA_SHOP_ID = os.getenv("YOOKASSA_SHOP_ID", "")
YOOKASSA_SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY", "")

# Базовые цены пакетов (₽) — используются в handlers (клавиатуры/платежи)
# и в analytics (детект покупок со скидкой)
BASE_PRICES = {
    "self":   {"base": 490, "extended": 990, "full": 1490},
    "money":  {"base": 390, "extended": 790, "full": 1190},
    "couple": {"base": 490, "extended": 990, "full": 1490},
}

BOT_USERNAME = os.getenv("BOT_USERNAME", "")
_admin_ids_raw = os.getenv("ADMIN_IDS", "")
ADMIN_IDS: list[int] = [int(x.strip()) for x in _admin_ids_raw.split(",") if x.strip().isdigit()]


# ─── WebApp «Спросить ОКО» ──────────────────────────────────────────────────────

# Публичный HTTPS-адрес мини-аппа (например https://oko.example.com).
# Пустое значение = кнопка чата не показывается в меню бота.
WEBAPP_URL = os.getenv("WEBAPP_URL", "").rstrip("/")

# Куда биндится aiohttp-сервис (за nginx достаточно localhost)
WEB_HOST = os.getenv("WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.getenv("WEB_PORT", "8080"))


def _int_env(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    return int(raw) if raw.lstrip("-").isdigit() else default


# Сколько вопросов пользователь может задать — по максимальному купленному
# пакету среди всех отчётов. demo = ещё ничего не купил.
CHAT_LIMITS = {
    "demo":     _int_env("CHAT_LIMIT_DEMO", 5),
    "base":     _int_env("CHAT_LIMIT_BASE", 30),
    "extended": _int_env("CHAT_LIMIT_EXTENDED", 60),
    "full":     _int_env("CHAT_LIMIT_FULL", 200),
}

# Сколько последних сообщений истории уходит в LLM
CHAT_HISTORY_MESSAGES = _int_env("CHAT_HISTORY_MESSAGES", 20)
# Потолок символов на контекст (профиль + блоки отчётов) в системном промпте
CHAT_CONTEXT_MAX_CHARS = _int_env("CHAT_CONTEXT_MAX_CHARS", 24000)
# Максимальная длина одного вопроса пользователя
CHAT_MAX_QUESTION_CHARS = _int_env("CHAT_MAX_QUESTION_CHARS", 1000)

