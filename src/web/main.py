"""Точка входа веб-сервиса «Спросить ОКО».

Запуск: python -m src.web.main
Хост и порт — WEB_HOST / WEB_PORT в .env (по умолчанию 127.0.0.1:8080,
наружу его публикует nginx с HTTPS).
"""
import logging

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

from src.web.app import run  # noqa: E402  — после load_dotenv и настройки логов


if __name__ == "__main__":
    run()
