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


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    if user:
        await message.answer(f"С возвращением, {user.name}! 👋")
        await state.clear()
        return

    await message.answer("Привет! Давай познакомимся. Пришли своё фото 📷")
    await state.set_state(RegistrationStates.waiting_for_photo)


@router.message(RegistrationStates.waiting_for_photo, F.photo)
async def process_photo(message: Message, state: FSMContext):
    photo: PhotoSize = message.photo[-1]  # самое большое разрешение
    await state.update_data(photo_file_id=photo.file_id)
    await message.answer("Отлично! Теперь напиши своё имя ✏️")
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
    await state.update_data(name=name)
    await message.answer(
        "Запомнил! Теперь напиши дату рождения в формате ДД.ММ.ГГГГ 🗓"
    )
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

    data = await state.get_data()
    async with async_session() as session:
        user = User(
            telegram_id=message.from_user.id,
            name=data["name"],
            photo_file_id=data["photo_file_id"],
            birth_date=birth_date,
        )
        session.add(user)
        await session.commit()

    await state.clear()
    await message.answer(
        f"Рад знакомству, {data['name']}! 🎉\n"
        "Твои данные сохранены. Добро пожаловать!"
    )


@router.message(RegistrationStates.waiting_for_birth_date)
async def process_birth_date_invalid(message: Message):
    await message.answer("Пожалуйста, напиши дату текстом в формате ДД.ММ.ГГГГ 🗓")