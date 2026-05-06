import asyncio
import json
import tempfile
from datetime import datetime

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, PhotoSize, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile,
)
from aiogram.fsm.context import FSMContext
from sqlalchemy import select

from src.bot.db import async_session, User
from src.bot.states import RegistrationStates

router = Router()


def _main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Портрет личности", callback_data="menu_self")],
        [InlineKeyboardButton(text="Совместимость пары", callback_data="menu_couple")],
        [InlineKeyboardButton(text="Денежная карта",    callback_data="menu_money")],
    ])


def _is_complete(user: User) -> bool:
    return bool(user.name and user.birth_date and user.face_json)


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


# ─── /start ────────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    if user:
        await state.clear()
        if _is_complete(user):
            await message.answer(
                f"С возвращением, {user.name}! 👋\nВыбери раздел:",
                reply_markup=_main_menu(),
            )
        else:
            await message.answer(f"С возвращением, {user.name}! 👋")
        return

    async with async_session() as session:
        new_user = User(telegram_id=message.from_user.id)
        session.add(new_user)
        await session.commit()

    await message.answer("Привет! Давай познакомимся. Пришли своё фото 📷")
    await state.set_state(RegistrationStates.waiting_for_photo)


# ─── Регистрация ────────────────────────────────────────────────────────────────

@router.message(RegistrationStates.waiting_for_photo, F.photo)
async def process_photo(message: Message, state: FSMContext):
    photo: PhotoSize = message.photo[-1]

    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        if user:
            user.photo_file_id = photo.file_id
            await session.commit()

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

    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        if user:
            user.birth_date = birth_date
            await session.commit()

    await state.clear()
    await message.answer(
        "Рад знакомству! 🎉 Данные сохранены.\n\nВыбери раздел:",
        reply_markup=_main_menu(),
    )


@router.message(RegistrationStates.waiting_for_birth_date)
async def process_birth_date_invalid(message: Message):
    await message.answer("Пожалуйста, напиши дату текстом в формате ДД.ММ.ГГГГ 🗓")


# ─── Главное меню ───────────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu_self")
async def cb_menu_self(callback: CallbackQuery):
    await callback.message.edit_text(
        "Портрет личности — анализ твоей внешности, нумерологии и психологических паттернов.\n\n"
        "Запустим тестовый анализ?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Запустить анализ", callback_data="run_self_demo")],
        ]),
    )
    await callback.answer()


@router.callback_query(F.data == "menu_couple")
async def cb_menu_couple(callback: CallbackQuery):
    await callback.message.edit_text("Раздел «Совместимость пары» скоро будет доступен.")
    await callback.answer()


@router.callback_query(F.data == "menu_money")
async def cb_menu_money(callback: CallbackQuery):
    await callback.message.edit_text("Раздел «Денежная карта» скоро будет доступен.")
    await callback.answer()


# ─── Запуск отчёта ──────────────────────────────────────────────────────────────

@router.callback_query(F.data == "run_self_demo")
async def cb_run_self_demo(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)

    if not user or not _is_complete(user):
        await callback.message.edit_text(
            "Для анализа нужны фото, имя и дата рождения. Пройди регистрацию: /start"
        )
        await callback.answer()
        return

    await callback.message.edit_text("Запускаю анализ... Это займёт минуту ⏳")
    await callback.answer()

    asyncio.create_task(_run_self_report(callback.message, user))


async def _run_self_report(message: Message, user: User):
    from src.api import generate_report

    try:
        face_data = json.loads(user.face_json)
        birthdate = user.birth_date.strftime("%d.%m.%Y")

        loop = asyncio.get_running_loop()
        html = await loop.run_in_executor(
            None,
            lambda: generate_report(
                report_type="self",
                face_data=face_data,
                name=user.name,
                birthdate=birthdate,
                plan="demo",
            ),
        )

        await message.delete()
        file = BufferedInputFile(html.encode("utf-8"), filename=f"portrait_{user.name}.html")
        await message.answer_document(file, caption="Твой портрет личности готов! 🎉")

    except Exception as e:
        await message.edit_text(f"Ошибка при генерации отчёта: {e}")
