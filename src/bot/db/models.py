from sqlalchemy import (
    Column, Integer, BigInteger, String, Date, Text, DateTime,
    Boolean, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase
from datetime import datetime, timezone


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=True)
    photo_file_id = Column(String(512), nullable=True)
    birth_date = Column(Date, nullable=True)
    face_json = Column(Text, nullable=True)
    palm_left_json = Column(Text, nullable=True)
    palm_right_json = Column(Text, nullable=True)

    # self report
    blocks_json = Column(Text, nullable=True)
    purchased_plan = Column(String(20), nullable=True)
    report_html = Column(Text, nullable=True)

    # money report
    money_blocks_json = Column(Text, nullable=True)
    money_plan = Column(String(20), nullable=True)
    money_html = Column(Text, nullable=True)

    # couple report
    partner_name = Column(String(255), nullable=True)
    partner_birth_date = Column(Date, nullable=True)
    partner_photo_file_id = Column(String(512), nullable=True)
    partner_face_json = Column(Text, nullable=True)
    partner_palm_left_json = Column(Text, nullable=True)
    partner_palm_right_json = Column(Text, nullable=True)
    couple_blocks_json = Column(Text, nullable=True)
    couple_plan = Column(String(20), nullable=True)
    couple_html = Column(Text, nullable=True)

    # referral
    referral_code = Column(String(20), unique=True, nullable=True, index=True)
    referred_by = Column(String(20), nullable=True, index=True)

    # notifications
    last_activity_at = Column(DateTime, nullable=True)
    is_blocked = Column(Boolean, nullable=False, default=False, server_default="0")

    # sale
    discount_percent = Column(Integer, nullable=False, default=0, server_default="0")


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    yookassa_id = Column(String(255), unique=True, nullable=False, index=True)
    telegram_id = Column(BigInteger, nullable=False, index=True)
    report_type = Column(String(20), nullable=False)
    plan = Column(String(20), nullable=False, default="base")
    amount = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    confirmation_url = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    paid_at = Column(DateTime, nullable=True)


class UserEvent(Base):
    """Append-only лог событий пользователя для системы пушей."""
    __tablename__ = "user_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, nullable=False, index=True)
    event_type = Column(String(40), nullable=False)
    report_type = Column(String(20), nullable=True)   # self/money/couple или None
    plan = Column(String(20), nullable=True)           # для purchase-событий
    payment_id = Column(String(255), nullable=True)    # для payment-событий
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    payload_json = Column(Text, nullable=True)


class NotificationLog(Base):
    """Журнал отправленных пушей — для идемпотентности."""
    __tablename__ = "notification_log"
    __table_args__ = (
        UniqueConstraint("telegram_id", "event_key", name="uq_notif_log"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, nullable=False, index=True)
    event_key = Column(String(60), nullable=False)
    sent_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
