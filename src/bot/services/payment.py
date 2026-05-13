"""YooKassa payment service — боевой режим."""

import logging
import os
import secrets
from yookassa import Configuration, Payment as YooPayment

log = logging.getLogger(__name__)

_configured = False


def _ensure_configured():
    """Lazy-инициализация конфигурации YooKassa (боевой режим)."""
    global _configured
    if not _configured:
        shop_id = os.environ.get("YOOKASSA_SHOP_ID", "")
        secret = os.environ.get("YOOKASSA_SECRET_KEY", "")
        if not shop_id or not secret:
            raise RuntimeError(
                "YOOKASSA_SHOP_ID и YOOKASSA_SECRET_KEY должны быть заданы в .env"
            )
        # Боевой режим — configure() без третьего аргумента
        Configuration.configure(shop_id, secret)
        _configured = True
        log.info("YooKassa SDK настроен (shop_id=%s, боевой режим)", shop_id)


# Маппинг: (report_type, plan) → {description}
PACKAGE_DESCRIPTIONS = {
    ("self", "base"): "Портрет личности · Базовый",
    ("self", "extended"): "Портрет личности · Расширенный",
    ("self", "full"): "Портрет личности · Премиум",
    ("money", "base"): "Денежная карта · Базовый",
    ("money", "extended"): "Денежная карта · Расширенный",
    ("money", "full"): "Денежная карта · Премиум",
    ("couple", "base"): "Совместимость пары · Базовый",
    ("couple", "extended"): "Совместимость пары · Расширенный",
    ("couple", "full"): "Совместимость пары · Премиум",
}


def _idempotence_key() -> str:
    """Сгенерировать уникальный ключ идемпотентности."""
    return secrets.token_hex(16)


def create_payment(report_type: str, plan: str, telegram_id: int, amount: str | None = None) -> YooPayment:
    """Создать платёж в YooKassa.

    Args:
        report_type: Тип отчёта (self / couple / money).
        plan: Пакет (base / extended / full).
        telegram_id: Telegram ID пользователя.
        amount: Сума платежа (строка вида "449.00").

    Returns:
        Объект Payment от YooKassa SDK.
    """
    _ensure_configured()

    description = PACKAGE_DESCRIPTIONS.get((report_type, plan))
    if not description:
        raise ValueError(f"Неизвестный пакет: {report_type}/{plan}")

    if not amount:
        raise ValueError(f"Сумма платежа не указана для {report_type}/{plan}")

    # Кассовый чек (54-ФЗ) — обязателен в боевом режиме YooKassa
    receipt = {
        "customer": {
            "email": f"tg_{telegram_id}@oko.bot",
        },
        "items": [
            {
                "description": description,
                "quantity": "1",
                "amount": {"value": amount, "currency": "RUB"},
                "vat_code": int(os.environ.get("YOOKASSA_VAT_CODE", "1")),
                "payment_mode": "full_payment",
                "payment_subject": "service",
            }
        ],
    }

    payment_payload = {
        "amount": {"value": amount, "currency": "RUB"},
        "confirmation": {
            "type": "redirect",
            "return_url": "https://t.me/",
        },
        "capture": True,
        "description": description,
        "receipt": receipt,
        "metadata": {
            "telegram_id": str(telegram_id),
            "report_type": report_type,
            "plan": plan,
        },
    }

    idem_key = _idempotence_key()

    log.info(
        "Создание платежа: amount=%s RUB, description=%s, telegram_id=%s, idem_key=%s",
        amount, description, telegram_id, idem_key,
    )

    try:
        payment = YooPayment.create(payment_payload, idem_key)
    except Exception as e:
        log.error(
            "YooKassa create_payment ОШИБКА: %s | payload=%s",
            e, payment_payload, exc_info=True,
        )
        raise

    log.info(
        "Платёж создан: id=%s, status=%s, confirmation_url=%s",
        payment.id,
        payment.status,
        payment.confirmation.confirmation_url if payment.confirmation else "N/A",
    )

    if not payment.confirmation or not getattr(payment.confirmation, "confirmation_url", None):
        log.error("Платёж %s: нет confirmation_url! payment=%s", payment.id, payment)
        raise RuntimeError(
            f"YooKassa не вернул URL для оплаты. Статус: {payment.status}. "
            f"Проверьте, что магазин активен и ключи верны."
        )

    return payment


def check_payment(payment_id: str) -> YooPayment:
    """Проверить статус платежа по ID."""
    _ensure_configured()
    log.info("Проверка статуса платежа %s", payment_id)
    try:
        result = YooPayment.find_one(payment_id)
        log.info("Статус платежа %s: %s", payment_id, result.status)
        return result
    except Exception as e:
        log.error("YooKassa check_payment ОШИБКА для %s: %s", payment_id, e, exc_info=True)
        raise