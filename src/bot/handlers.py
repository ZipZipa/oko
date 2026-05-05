import asyncio
import json
import tempfile
from datetime import datetime

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, PhotoSize
from aiogram.fsm.context import FSMContext
from sqlalchemy import select

from src.bot.db import async_session, User
from src.bot.states import RegistrationStates

router = Router()


async def get_user(telegram_id: int) -> User | None:
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()


async def _analyze_and_save_face(bot, file_id: str, telegram_id: int):
    """Фоновая задача: скачивает фото, анализирует лицо, записывает face_json в БД."""
    from src.core.face_analyzer import analyze_face
    import os

    try:
        file = await bot.get_file(file_id)
        if not file.file_path:
            return

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            await bot.download_file(file.file_path, tmp.name)
            tmp_path = tmp.name

        try:
            face_data = analyze_face(tmp_path)
        finally:
            os.unlink(tmp_path)

        if face_data:
            async with async_session() as session:
                result = await session.execute(
                    select(User).where(User.telegram_id == telegram_id)
                )
                user = result.scalar_one_or_none()
                if user:
                    user.face_json = json.dumps(face_data, ensure_ascii=False)
                    await session.commit()
    except Exception:
        pass


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    if user:
        await message.answer(f"С возвращением, {user.name}! 👋")
        await state.clear()
        return

    # Создаём пустую запись в БД сразу при /start
    async with async_session() as session:
        new_user = User(telegram_id=message.from_user.id)
        session.add(new_user)
        await session.commit()

    await message.answer("Привет! Давай познакомимся. Пришли своё фото 📷")
    await state.set_state(RegistrationStates.waiting_for_photo)


@router.message(RegistrationStates.waiting_for_photo, F.photo)
async def process_photo(message: Message, state: FSMContext):
    photo: PhotoSize = message.photo[-1]

    # Сохраняем photo_file_id в БД
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        if user:
            user.photo_file_id = photo.file_id
            await session.commit()

    # Запускаем анализ лица в фоне
    asyncio.create_task(
        _analyze_and_save_face(message.bot, photo.file_id, message.from_user.id)
    )

    await message.answer("Фото получено! 📷 Напиши своё имя ✏️")
    await state.set_state(RegistrationStates.waiting_for_name)


@router.message(RegistrationStates.waiting_for_photo)
async def process_photo_invalid(message: Message):
    await message.answer("Пожалуйста, пришли именно фото 📷")


@router.message(RegistrationStates.waiting_for_name, F.text)
async def process_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if not name:
        await message.answer("Имя не может быть пустым. Попробуй ещё раз ✏️")
        return

    # Сохраняем имя в БД
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        if user:
            user.name = name
            await session.commit()

    await message.answer("Запомнил! Теперь напиши дату рождения в формате ДД.ММ.ГГГГ 🗓")
    await state.set_state(RegistrationStates.waiting_for_birth_date)


@router.message(RegistrationStates.waiting_for_name)
async def process_name_invalid(message: Message):
    await message.answer("Пожалуйста, напиши имя текстом ✏️")


@router.message(RegistrationStates.waiting_for_birth_date, F.text)
async def process_birth_date(message: Message, state: FSMContext):
    try:
        birth_date = datetime.strptime(message.text.strip(), "%d.%m.%Y").date()
    except ValueError:
        await message.answer(
            "Неверный формат. Напиши дату в формате ДД.ММ.ГГГГ, например 15.06.1990 🗓"
        )
        return

    # Сохраняем дату рождения в БД
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        if user:
            user.birth_date = birth_date
            await session.commit()

    await state.clear()
    await message.answer(f"Рад знакомству! 🎉 Твои данные сохранены. Добро пожаловать!")


@router.message(RegistrationStates.waiting_for_birth_date)
async def process_birth_date_invalid(message: Message):
    await message.answer("Пожалуйста, напиши дату текстом в формате ДД.ММ.ГГГГ 🗓")