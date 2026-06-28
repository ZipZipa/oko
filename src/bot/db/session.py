from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.bot.config import DATABASE_URL
from src.bot.db.models import Base

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        new_cols = [
            "blocks_json TEXT",
            "purchased_plan VARCHAR(20)",
            "report_html TEXT",
            "money_blocks_json TEXT",
            "money_plan VARCHAR(20)",
            "money_html TEXT",
            "partner_name VARCHAR(255)",
            "partner_birth_date DATE",
            "partner_photo_file_id VARCHAR(512)",
            "partner_face_json TEXT",
            "couple_blocks_json TEXT",
            "couple_plan VARCHAR(20)",
            "couple_html TEXT",
            "palm_left_json TEXT",
            "palm_right_json TEXT",
            "partner_palm_left_json TEXT",
            "partner_palm_right_json TEXT",
            "referral_code VARCHAR(20)",
            "referred_by VARCHAR(20)",
            "last_activity_at DATETIME",
            "is_blocked BOOLEAN DEFAULT 0",
            "discount_percent INTEGER DEFAULT 0",
        ]
        for col in new_cols:
            try:
                await conn.execute(text(f"ALTER TABLE users ADD COLUMN {col}"))
            except Exception:
                pass


async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session