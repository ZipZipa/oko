from sqlalchemy import Column, Integer, BigInteger, String, Date, Text
from sqlalchemy.orm import DeclarativeBase


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
    blocks_json = Column(Text, nullable=True)
    purchased_plan = Column(String(20), nullable=True)
    report_html = Column(Text, nullable=True)
