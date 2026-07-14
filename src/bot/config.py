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
