"""Поллинг pending-платежей через YooKassa.

Пользователь может оплатить через web и не нажать «Я оплатил».
Чтобы корректно отменять E5 и запускать E6/E7, periodically опрашиваем
старые pending-платежи и обновляем их статус.
"""
import asyncio
import logging

from datetime import datetime, timezone, timedelta
from sqlalchemy import select

from src.bot.db import async_session, Payment
from src.bot.notifications.events import mark_purchase_completed

log = logging.getLogger(__name__)

# Не трогать платежи младше этого порога — даём пользователю время
# нажать «Я оплатил» самому.
_MIN_AGE = timedelta(minutes=5)


async def poll_pending_payments() -> None:
    """Проверить все pending-платежи старше _MIN_AGE через YooKassa API."""
    from src.bot.services.payment import check_payment

    try:
        async with async_session() as session:
            result = await session.execute(
                select(Payment).where(Payment.status == "pending")
            )
            pending = result.scalars().all()
    except Exception:
        log.error("poll_pending_payments: select failed", exc_info=True)
        return

    now = datetime.now(timezone.utc)
    for payment in pending:
        created = payment.created_at or now
        if now - created < _MIN_AGE:
            continue

        try:
            yoo = await asyncio.get_running_loop().run_in_executor(
                None, lambda p=payment: check_payment(p.yookassa_id)
            )
        except Exception:
            log.error("poll: check_payment failed %s", payment.yookassa_id, exc_info=True)
            continue

        if yoo.status == payment.status:
            continue

        try:
            async with async_session() as session:
                result = await session.execute(
                    select(Payment).where(Payment.yookassa_id == payment.yookassa_id)
                )
                db_payment = result.scalar_one_or_none()
                if db_payment and db_payment.status != yoo.status:
                    db_payment.status = yoo.status
                    if yoo.status == "succeeded":
                        db_payment.paid_at = datetime.now(timezone.utc)
                    await session.commit()

            if yoo.status == "succeeded":
                await mark_purchase_completed(
                    payment.telegram_id,
                    payment.report_type,
                    payment.plan,
                    payment.yookassa_id,
                )
                log.info(
                    "poll: silent payment succeeded tg=%s report=%s plan=%s",
                    payment.telegram_id, payment.report_type, payment.plan,
                )
        except Exception:
            log.error("poll: update failed %s", payment.yookassa_id, exc_info=True)
