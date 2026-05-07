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


# ─── Меню ───────────────────────────────────────────────────────────────────────

def _main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Портрет личности", callback_data="menu_self")],
        [InlineKeyboardButton(text="Совместимость пары", callback_data="menu_couple")],
        [InlineKeyboardButton(text="Денежная карта",    callback_data="menu_money")],
    ])


_PLAN_LEVEL = {"demo": 0, "base": 1, "extended": 2, "full": 3}

_PACKAGES = {
    "base": {
        "label": "Базовый",
        "text": (
            "Базовый пакет\n\n"
            "Включает всё из демо, плюс два закрытых раздела:\n"
            "• Ошибка, которая тормозит жизнь — паттерн, который мешает двигаться вперёд\n"
            "• Сценарий в отношениях — как ты строишь близкие связи и где ломаешься"
        ),
    },
    "extended": {
        "label": "Расширенный",
        "text": (
            "Расширенный пакет\n\n"
            "Всё из Базового, плюс:\n"
            "• Жизненные сценарии — глубокие программы, которые управляют твоими решениями\n"
            "• Кармический урок — то, что повторяется до тех пор, пока не осознано"
        ),
    },
    "full": {
        "label": "Премиум",
        "text": (
            "Премиум пакет\n\n"
            "Полный отчёт — все блоки без ограничений:\n"
            "• Скрытый талант — ресурс, который ты скорее всего недооцениваешь\n"
            "• Скрытая правда — то, что проявляется, когда уходит контроль\n"
            "• Сводный портрет — итоговый психологический профиль"
        ),
    },
}


def _packages_menu(above_plan: str = "demo") -> InlineKeyboardMarkup:
    current_level = _PLAN_LEVEL.get(above_plan, 0)
    rows = [
        [InlineKeyboardButton(text=pkg["label"], callback_data=f"pkg_{key}")]
        for key, pkg in _PACKAGES.items()
        if _PLAN_LEVEL[key] > current_level
    ]
    rows.append([InlineKeyboardButton(text="← В меню", callback_data="back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _package_detail_menu(plan_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Купить", callback_data=f"buy_{plan_key}")],
        [InlineKeyboardButton(text="← Назад к пакетам", callback_data="show_packages")],
    ])


# ─── Хелперы БД ─────────────────────────────────────────────────────────────────

def _is_complete(user: User) -> bool:
    return bool(user.name and user.birth_date and user.face_json)


async def get_user(telegram_id: int) -> User | None:
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()


# ─── Фоновый анализ лица ────────────────────────────────────────────────────────

async def _analyze_and_save_face(bot, file_id: str, telegram_id: int):
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

async def _edit_to_packages(message, user: User):
    purchased = (user.purchased_plan if user else None) or "demo"
    menu = _packages_menu(above_plan=purchased)
    if menu.inline_keyboard[:-1]:  # есть хоть один пакет помимо кнопки "← В меню"
        await message.edit_text("Выбери пакет:", reply_markup=menu)
    else:
        await message.edit_text(
            "Это максимальный пакет.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="← В меню", callback_data="back_to_main")],
            ]),
        )


@router.callback_query(F.data == "menu_self")
async def cb_menu_self(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)

    if user and user.blocks_json:
        await _edit_to_packages(callback.message, user)
    else:
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


# ─── Пакеты ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "back_to_main")
async def cb_back_to_main(callback: CallbackQuery):
    await callback.message.edit_text(
        "Выбери раздел:",
        reply_markup=_main_menu(),
    )
    await callback.answer()


@router.callback_query(F.data == "show_packages")
async def cb_show_packages(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    await _edit_to_packages(callback.message, user)
    await callback.answer()


@router.callback_query(F.data.in_({"pkg_base", "pkg_extended", "pkg_full"}))
async def cb_package_detail(callback: CallbackQuery):
    plan_key = callback.data.removeprefix("pkg_")
    pkg = _PACKAGES[plan_key]
    await callback.message.edit_text(
        pkg["text"],
        reply_markup=_package_detail_menu(plan_key),
    )
    await callback.answer()


# ─── Запуск отчёта ──────────────────────────────────────────────────────────────

@router.callback_query(F.data == "run_self_demo")
async def cb_run_self_demo(callback: CallbackQuery):
    await _start_report(callback, plan="demo")


@router.callback_query(F.data.in_({"buy_base", "buy_extended", "buy_full"}))
async def cb_buy(callback: CallbackQuery):
    plan_key = callback.data.removeprefix("buy_")
    await _start_report(callback, plan=plan_key)


async def _start_report(callback: CallbackQuery, plan: str):
    user = await get_user(callback.from_user.id)

    if not user or not _is_complete(user):
        await callback.message.edit_text(
            "Для анализа нужны фото, имя и дата рождения. Пройди регистрацию: /start"
        )
        await callback.answer()
        return

    await callback.message.edit_text("Запускаю анализ... Это займёт минуту ⏳")
    await callback.answer()

    asyncio.create_task(_run_self_report(callback.message, user, plan))


async def _run_self_report(message: Message, user: User, plan: str):
    from src.api import generate_report

    try:
        face_data = json.loads(user.face_json)
        birthdate = user.birth_date.strftime("%d.%m.%Y")
        loop = asyncio.get_running_loop()

        if plan == "demo":
            out_blocks: list = []
            html = await loop.run_in_executor(
                None,
                lambda: generate_report(
                    report_type="self",
                    face_data=face_data,
                    name=user.name,
                    birthdate=birthdate,
                    plan="demo",
                    _out_blocks=out_blocks,
                ),
            )
            if out_blocks:
                async with async_session() as session:
                    result = await session.execute(
                        select(User).where(User.telegram_id == user.telegram_id)
                    )
                    db_user = result.scalar_one_or_none()
                    if db_user:
                        db_user.blocks_json = json.dumps(out_blocks[0], ensure_ascii=False)
                        await session.commit()
        else:
            reference = user.blocks_json or None
            html = await loop.run_in_executor(
                None,
                lambda: generate_report(
                    report_type="self",
                    face_data=face_data,
                    name=user.name,
                    birthdate=birthdate,
                    plan=plan,
                    reference=reference,
                ),
            )

        if plan != "demo":
            async with async_session() as session:
                result = await session.execute(
                    select(User).where(User.telegram_id == user.telegram_id)
                )
                db_user = result.scalar_one_or_none()
                if db_user and _PLAN_LEVEL.get(plan, 0) > _PLAN_LEVEL.get(db_user.purchased_plan or "demo", 0):
                    db_user.purchased_plan = plan
                    db_user.report_html = html
                    await session.commit()

        _plan_label = {"demo": "Демо", "base": "Базовый", "extended": "Расширенный", "full": "Премиум"}
        caption = f"Портрет личности · {_plan_label.get(plan, plan)} готов!"

        await message.delete()
        file = BufferedInputFile(html.encode("utf-8"), filename=f"Портрет личности {_plan_label.get(plan, plan)}.html")
        await message.answer_document(file, caption=caption)

        menu = _packages_menu(above_plan=plan)
        if menu.inline_keyboard[:-1]:  # есть пакеты выше текущего плана
            await message.answer("Выбери пакет:", reply_markup=menu)
        else:
            await message.answer(
                "Это максимальный пакет.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="← В меню", callback_data="back_to_main")],
                ]),
            )

    except Exception as e:
        await message.edit_text(f"Ошибка при генерации отчёта: {e}")
