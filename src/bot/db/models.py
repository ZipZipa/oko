from sqlalchemy import Column, Integer, BigInteger, String, Date, Text, DateTime
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
    partner_face_json = Column(Text, nullable=True)
    couple_blocks_json = Column(Text, nullable=True)
    couple_plan = Column(String(20), nullable=True)
    couple_html = Column(Text, nullable=True)

    # referral
    referral_code = Column(String(20), unique=True, nullable=True, index=True)
    referred_by = Column(String(20), nullable=True, index=True)


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
