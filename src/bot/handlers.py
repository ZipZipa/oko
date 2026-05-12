import asyncio
import base64
import html as html_mod
import json
import tempfile
from datetime import datetime

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, PhotoSize, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile,
)
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from sqlalchemy import select

from src.bot.db import async_session, User
from src.bot.states import RegistrationStates, PalmStates, PartnerStates
from src.bot.messages import send_msg, edit_msg, MESSAGES

router = Router()


# ─── Меню ───────────────────────────────────────────────────────────────────────

def _main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Портрет личности", callback_data="menu_self")],
        [InlineKeyboardButton(text="Совместимость пары", callback_data="menu_couple")],
        [InlineKeyboardButton(text="Денежная карта",    callback_data="menu_money")],
    ])


def _cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="← Отмена", callback_data="back_to_main")],
    ])


def _skip_palms_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пропустить →", callback_data="skip_palms")],
        [InlineKeyboardButton(text="← Отмена", callback_data="back_to_main")],
    ])


_PLAN_LEVEL = {"demo": 0, "base": 1, "extended": 2, "full": 3}

# ── Лейблы пакетов (текст берётся из MESSAGES) ──────────────────────────────────
_PACKAGE_NAMES = {"base": "Базовый", "extended": "Расширенный", "full": "Премиум"}

_BASE_PRICES = {"base": 249, "extended": 449, "full": 649}

# Скидки при апгрейде: (текущий_пакет, целевой_пакет) → процент скидки
_UPGRADE_DISCOUNTS = {
    ("base", "extended"): 25,
    ("base", "full"): 50,
    ("extended", "full"): 25,
}


def _get_discounted_price(current_plan: str, target_plan: str) -> int:
    """Цена с учётом скидки за уже купленный пакет."""
    base_price = _BASE_PRICES.get(target_plan, 0)
    discount_pct = _UPGRADE_DISCOUNTS.get((current_plan, target_plan), 0)
    if discount_pct:
        return round(base_price * (100 - discount_pct) / 100)
    return base_price

# Маппинг: (report_prefix, plan_key) → ключ в MESSAGES
_PACKAGE_MSG_KEYS = {
    ("self", "base"): "pkg_self_base",
    ("self", "extended"): "pkg_self_extended",
    ("self", "full"): "pkg_self_full",
    ("money", "base"): "pkg_money_base",
    ("money", "extended"): "pkg_money_extended",
    ("money", "full"): "pkg_money_full",
    ("couple", "base"): "pkg_couple_base",
    ("couple", "extended"): "pkg_couple_extended",
    ("couple", "full"): "pkg_couple_full",
}


def _packages_menu(above_plan: str = "demo", report_prefix: str = "self") -> InlineKeyboardMarkup:
    current_level = _PLAN_LEVEL.get(above_plan, 0)
    rows = []
    for key in ("base", "extended", "full"):
        if _PLAN_LEVEL[key] > current_level:
            name = _PACKAGE_NAMES[key]
            price = _get_discounted_price(above_plan, key)
            discount_pct = _UPGRADE_DISCOUNTS.get((above_plan, key), 0)
            if discount_pct:
                label = f"{name} · {price} ₽ 🎁"
            else:
                label = f"{name} · {price} ₽"
            rows.append([InlineKeyboardButton(text=label, callback_data=f"pkg_{report_prefix}_{key}")])
    rows.append([InlineKeyboardButton(text="← В меню", callback_data="back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _package_detail_menu(report_prefix: str, plan_key: str, current_plan: str = "demo") -> InlineKeyboardMarkup:
    price = _get_discounted_price(current_plan, plan_key)
    buy_text = f"Купить · {price} ₽"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=buy_text, callback_data=f"buy_{report_prefix}_{plan_key}")],
        [InlineKeyboardButton(text="← Назад к пакетам", callback_data=f"show_packages_{report_prefix}")],
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


async def _analyze_face_return(bot, file_id: str) -> dict | None:
    """Скачивает и анализирует лицо, возвращает dict или None."""
    from src.core.face_analyzer import analyze_face
    import os

    try:
        file = await bot.get_file(file_id)
        if not file.file_path:
            return None
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            await bot.download_file(file.file_path, tmp.name)
            tmp_path = tmp.name
        try:
            loop = asyncio.get_running_loop()
            face_data = await loop.run_in_executor(None, lambda: analyze_face(tmp_path))
        finally:
            os.unlink(tmp_path)
        return face_data
    except Exception:
        return None


# ─── /start ────────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    if user:
        await state.clear()
        if _is_complete(user):
            await send_msg(message, "choose_section", reply_markup=_main_menu())
        else:
            await send_msg(message, "start_returning_incomplete", name=user.name)
        return

    async with async_session() as session:
        new_user = User(telegram_id=message.from_user.id)
        session.add(new_user)
        await session.commit()

    await send_msg(message, "start_new")
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

    await send_msg(message, "photo_received")
    await state.set_state(RegistrationStates.waiting_for_name)


@router.message(RegistrationStates.waiting_for_photo)
async def process_photo_invalid(message: Message):
    await send_msg(message, "photo_invalid")


@router.message(RegistrationStates.waiting_for_name, F.text)
async def process_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if not name:
        await send_msg(message, "name_empty")
        return

    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        if user:
            user.name = name
            await session.commit()

    await send_msg(message, "name_saved")
    await state.set_state(RegistrationStates.waiting_for_birth_date)


@router.message(RegistrationStates.waiting_for_name)
async def process_name_invalid(message: Message):
    await send_msg(message, "name_invalid")


@router.message(RegistrationStates.waiting_for_birth_date, F.text)
async def process_birth_date(message: Message, state: FSMContext):
    try:
        birth_date = datetime.strptime(message.text.strip(), "%d.%m.%Y").date()
    except ValueError:
        await send_msg(message, "birthdate_invalid")
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
    await send_msg(message, "registration_complete", reply_markup=_main_menu())


@router.message(RegistrationStates.waiting_for_birth_date)
async def process_birth_date_invalid(message: Message):
    await send_msg(message, "birthdate_invalid_type")


# ─── Главное меню ───────────────────────────────────────────────────────────────

async def _edit_to_packages(message: Message, user: User, report_prefix: str):
    plan_field = {"self": "purchased_plan", "money": "money_plan", "couple": "couple_plan"}[report_prefix]
    purchased = getattr(user, plan_field, None) or "demo"
    menu = _packages_menu(above_plan=purchased, report_prefix=report_prefix)
    if menu.inline_keyboard[:-1]:
        await edit_msg(message, "choose_package", reply_markup=menu)
    else:
        await edit_msg(message, "max_package", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="← В меню", callback_data="back_to_main")],
        ]))


@router.callback_query(F.data == "menu_self")
async def cb_menu_self(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)

    if user and user.blocks_json:
        await _edit_to_packages(callback.message, user, "self")
    else:
        await edit_msg(
            callback.message, "self_intro",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Запустить анализ", callback_data="run_self_demo")],
                [InlineKeyboardButton(text="← В меню", callback_data="back_to_main")],
            ]),
        )
    await callback.answer()


@router.callback_query(F.data == "menu_money")
async def cb_menu_money(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)

    if not user or not _is_complete(user):
        await edit_msg(callback.message, "incomplete_profile")
        await callback.answer()
        return

    if user and user.money_blocks_json:
        await _edit_to_packages(callback.message, user, "money")
    else:
        await edit_msg(
            callback.message, "money_intro",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Запустить анализ", callback_data="run_money_demo")],
                [InlineKeyboardButton(text="← В меню", callback_data="back_to_main")],
            ]),
        )
    await callback.answer()


@router.callback_query(F.data == "menu_couple")
async def cb_menu_couple(callback: CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)

    if not user or not _is_complete(user):
        await edit_msg(callback.message, "incomplete_profile")
        await callback.answer()
        return

    if user and user.couple_blocks_json:
        await _edit_to_packages(callback.message, user, "couple")
    else:
        await edit_msg(
            callback.message, "couple_intro",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="← Отмена", callback_data="back_to_main")],
            ]),
        )
        await state.set_state(PartnerStates.waiting_for_partner_name)
    await callback.answer()


# ─── Пакеты ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "back_to_main")
async def cb_back_to_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await edit_msg(callback.message, "choose_section", reply_markup=_main_menu())
    await callback.answer()


@router.callback_query(F.data == "skip_palms")
async def cb_skip_palms(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.clear()

    user = await get_user(callback.from_user.id)
    pending_plan = data.get("pending_plan", "full")
    report_type = data.get("pending_report_type", "self")

    status_msg = await edit_msg(callback.message, "analyzing")
    await callback.answer()

    if report_type == "money":
        asyncio.create_task(_run_money_report(status_msg, user, pending_plan))
    else:
        asyncio.create_task(_run_self_report(status_msg, user, pending_plan))


@router.callback_query(F.data.in_({"show_packages_self", "show_packages_money", "show_packages_couple"}))
async def cb_show_packages(callback: CallbackQuery):
    prefix = callback.data.removeprefix("show_packages_")
    user = await get_user(callback.from_user.id)
    await _edit_to_packages(callback.message, user, prefix)
    await callback.answer()


@router.callback_query(F.data.startswith("pkg_"))
async def cb_package_detail(callback: CallbackQuery):
    # pkg_self_base | pkg_money_extended | pkg_couple_full
    parts = callback.data.split("_", 2)
    if len(parts) != 3:
        await callback.answer()
        return
    _, report_prefix, plan_key = parts
    msg_key = _PACKAGE_MSG_KEYS.get((report_prefix, plan_key))
    if not msg_key:
        await callback.answer()
        return

    user = await get_user(callback.from_user.id)
    plan_field = {"self": "purchased_plan", "money": "money_plan", "couple": "couple_plan"}[report_prefix]
    current_plan = getattr(user, plan_field, None) or "demo" if user else "demo"

    discount_pct = _UPGRADE_DISCOUNTS.get((current_plan, plan_key), 0)
    markup = _package_detail_menu(report_prefix, plan_key, current_plan)

    if discount_pct:
        price = _get_discounted_price(current_plan, plan_key)
        base_price = _BASE_PRICES[plan_key]
        text = MESSAGES[msg_key].text
        text = text.replace(f"— {base_price} ₽", f"— <s>{base_price} ₽</s> {price} ₽", 1)
        try:
            await callback.message.edit_text(text=text, reply_markup=markup, parse_mode="HTML")
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e):
                raise
    else:
        await edit_msg(callback.message, msg_key, reply_markup=markup)
    await callback.answer()


# ─── Сбор данных партнёра (FSM для couple) ──────────────────────────────────────

@router.message(PartnerStates.waiting_for_partner_name, F.text)
async def process_partner_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if not name:
        await send_msg(message, "partner_name_empty", reply_markup=_cancel_keyboard())
        return

    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        if user:
            user.partner_name = name
            await session.commit()

    await state.set_state(PartnerStates.waiting_for_partner_birthdate)
    await send_msg(
        message, "partner_name_saved", name=name,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="← Отмена", callback_data="back_to_main")],
        ]),
    )


@router.message(PartnerStates.waiting_for_partner_name)
async def process_partner_name_invalid(message: Message):
    await send_msg(message, "partner_name_invalid", reply_markup=_cancel_keyboard())


@router.message(PartnerStates.waiting_for_partner_birthdate, F.text)
async def process_partner_birthdate(message: Message, state: FSMContext):
    try:
        birth_date = datetime.strptime(message.text.strip(), "%d.%m.%Y").date()
    except ValueError:
        await send_msg(
            message, "partner_birthdate_invalid",
            reply_markup=_cancel_keyboard(),
        )
        return

    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        if user:
            user.partner_birth_date = birth_date
            await session.commit()

    await state.set_state(PartnerStates.waiting_for_partner_photo)
    await send_msg(
        message, "partner_photo_request",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Пропустить →", callback_data="skip_partner_photo")],
            [InlineKeyboardButton(text="← Отмена", callback_data="back_to_main")],
        ]),
    )


@router.message(PartnerStates.waiting_for_partner_birthdate)
async def process_partner_birthdate_invalid(message: Message):
    await send_msg(message, "partner_birthdate_invalid_type", reply_markup=_cancel_keyboard())


@router.message(PartnerStates.waiting_for_partner_photo, F.photo)
async def process_partner_photo(message: Message, state: FSMContext):
    photo: PhotoSize = message.photo[-1]
    processing_msg = await send_msg(message, "analyzing_partner_photo")

    face_data = await _analyze_face_return(message.bot, photo.file_id)

    if face_data:
        async with async_session() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == message.from_user.id)
            )
            user = result.scalar_one_or_none()
            if user:
                user.partner_face_json = json.dumps(face_data, ensure_ascii=False)
                await session.commit()

    try:
        await processing_msg.delete()
    except TelegramBadRequest:
        pass
    await state.clear()

    user = await get_user(message.from_user.id)
    status_msg = await send_msg(message, "partner_data_received")
    asyncio.create_task(_run_couple_report(status_msg, user, "demo"))


@router.message(PartnerStates.waiting_for_partner_photo)
async def process_partner_photo_invalid(message: Message):
    await send_msg(
        message, "partner_photo_invalid",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Пропустить →", callback_data="skip_partner_photo")],
            [InlineKeyboardButton(text="← Отмена", callback_data="back_to_main")],
        ]),
    )


@router.callback_query(F.data == "skip_partner_photo")
async def cb_skip_partner_photo(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user = await get_user(callback.from_user.id)
    status_msg = await edit_msg(callback.message, "analyzing_couple_short")
    asyncio.create_task(_run_couple_report(status_msg, user, "demo"))
    await callback.answer()


# ─── Запуск отчётов ──────────────────────────────────────────────────────────────

@router.callback_query(F.data == "run_self_demo")
async def cb_run_self_demo(callback: CallbackQuery, state: FSMContext):
    await _start_self_report(callback, plan="demo", state=state)


@router.callback_query(F.data == "run_money_demo")
async def cb_run_money_demo(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    if not user or not _is_complete(user):
        await edit_msg(callback.message, "incomplete_profile")
        await callback.answer()
        return
    status_msg = await edit_msg(callback.message, "analyzing")
    await callback.answer()
    asyncio.create_task(_run_money_report(status_msg, user, "demo"))


@router.callback_query(F.data.startswith("buy_"))
async def cb_buy(callback: CallbackQuery, state: FSMContext):
    # buy_self_base | buy_money_extended | buy_couple_full
    parts = callback.data.split("_", 2)
    if len(parts) != 3:
        await callback.answer()
        return
    _, report_prefix, plan_key = parts

    user = await get_user(callback.from_user.id)
    if not user or not _is_complete(user):
        await edit_msg(callback.message, "incomplete_profile")
        await callback.answer()
        return

    if report_prefix == "self":
        await _start_self_report(callback, plan=plan_key, state=state)
    elif report_prefix == "money":
        if plan_key == "full":
            has_both_palms = bool(user.palm_left_json and user.palm_right_json)
            if not has_both_palms:
                await state.set_state(PalmStates.waiting_for_palm_left)
                await state.update_data(pending_plan=plan_key, pending_report_type="money")
                await edit_msg(
                    callback.message, "palm_needed_money",
                    reply_markup=_skip_palms_keyboard(),
                )
                await callback.answer()
                return
        status_msg = await edit_msg(callback.message, "analyzing")
        await callback.answer()
        asyncio.create_task(_run_money_report(status_msg, user, plan_key))
    elif report_prefix == "couple":
        status_msg = await edit_msg(callback.message, "analyzing_couple")
        await callback.answer()
        asyncio.create_task(_run_couple_report(status_msg, user, plan_key))


async def _start_self_report(callback: CallbackQuery, plan: str, state: FSMContext):
    user = await get_user(callback.from_user.id)

    if not user or not _is_complete(user):
        await edit_msg(callback.message, "incomplete_profile")
        await callback.answer()
        return

    if plan == "full":
        has_both_palms = bool(user.palm_left_json and user.palm_right_json)
        if not has_both_palms:
            await state.set_state(PalmStates.waiting_for_palm_left)
            await state.update_data(pending_plan=plan, pending_report_type="self")
            await edit_msg(
                callback.message, "palm_needed_self",
                reply_markup=_skip_palms_keyboard(),
            )
            await callback.answer()
            return

    status_msg = await edit_msg(callback.message, "analyzing")
    await callback.answer()

    asyncio.create_task(_run_self_report(status_msg, user, plan))


# ─── Сбор ладоней (FSM для Премиум self) ────────────────────────────────────────

async def _download_and_analyze_palm(bot, file_id: str) -> dict | None:
    from src.core.palm_analyzer import analyze_palm
    import os

    try:
        file = await bot.get_file(file_id)
        if not file.file_path:
            return None
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            await bot.download_file(file.file_path, tmp.name)
            tmp_path = tmp.name
        try:
            loop = asyncio.get_running_loop()
            palm_data = await loop.run_in_executor(None, lambda: analyze_palm(tmp_path))
        finally:
            os.unlink(tmp_path)
        return palm_data
    except Exception:
        return None


@router.message(PalmStates.waiting_for_palm_left, F.photo)
async def process_palm_left(message: Message, state: FSMContext):
    photo: PhotoSize = message.photo[-1]
    processing_msg = await send_msg(message, "palm_left_analyzing")

    palm_data = await _download_and_analyze_palm(message.bot, photo.file_id)

    if not palm_data:
        try:
            await processing_msg.delete()
        except TelegramBadRequest:
            pass
        await send_msg(message, "palm_not_detected", reply_markup=_skip_palms_keyboard())
        return

    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        if user:
            user.palm_left_json = json.dumps(palm_data, ensure_ascii=False)
            await session.commit()

    try:
        await processing_msg.delete()
    except TelegramBadRequest:
        pass
    await state.set_state(PalmStates.waiting_for_palm_right)
    await send_msg(message, "palm_left_accepted", reply_markup=_skip_palms_keyboard())


@router.message(PalmStates.waiting_for_palm_left)
async def process_palm_left_invalid(message: Message):
    await send_msg(message, "palm_photo_invalid", reply_markup=_skip_palms_keyboard())


@router.message(PalmStates.waiting_for_palm_right, F.photo)
async def process_palm_right(message: Message, state: FSMContext):
    photo: PhotoSize = message.photo[-1]
    processing_msg = await send_msg(message, "palm_right_analyzing")

    palm_data = await _download_and_analyze_palm(message.bot, photo.file_id)

    if not palm_data:
        try:
            await processing_msg.delete()
        except TelegramBadRequest:
            pass
        await send_msg(message, "palm_not_detected", reply_markup=_skip_palms_keyboard())
        return

    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        if user:
            user.palm_right_json = json.dumps(palm_data, ensure_ascii=False)
            await session.commit()

    data = await state.get_data()
    await state.clear()

    user = await get_user(message.from_user.id)

    try:
        await processing_msg.delete()
    except TelegramBadRequest:
        pass
    status_msg = await send_msg(message, "palm_both_accepted")
    pending_plan = data.get("pending_plan", "full")
    if data.get("pending_report_type") == "money":
        asyncio.create_task(_run_money_report(status_msg, user, pending_plan))
    else:
        asyncio.create_task(_run_self_report(status_msg, user, pending_plan))


@router.message(PalmStates.waiting_for_palm_right)
async def process_palm_right_invalid(message: Message):
    await send_msg(message, "palm_photo_invalid", reply_markup=_skip_palms_keyboard())


# ─── Вспомогательные ────────────────────────────────────────────────────────────

async def _download_photo_data_uri(bot, file_id: str) -> str | None:
    try:
        file = await bot.get_file(file_id)
        buf = await bot.download_file(file.file_path)
        data = base64.b64encode(buf.read()).decode("ascii")
        return f"data:image/jpeg;base64,{data}"
    except Exception:
        return None


async def _send_report(message: Message, html: str, caption: str, plan: str,
                       report_prefix: str, filename: str):
    """Отправляет HTML как документ, пинует, показывает пакеты выше."""
    plan_field = {"self": "purchased_plan", "money": "money_plan", "couple": "couple_plan"}[report_prefix]
    user = await get_user(message.chat.id)
    current_plan = getattr(user, plan_field, None) or plan

    try:
        await message.delete()
    except TelegramBadRequest:
        pass  # сообщение уже удалено (например, при переходе фото→текст через edit_msg)
    file = BufferedInputFile(html.encode("utf-8"), filename=filename)
    sent = await message.answer_document(file, caption=caption, parse_mode="HTML")
    await message.bot.pin_chat_message(chat_id=sent.chat.id, message_id=sent.message_id, disable_notification=True)

    menu = _packages_menu(above_plan=current_plan, report_prefix=report_prefix)
    if menu.inline_keyboard[:-1]:
        await send_msg(message, "choose_package", reply_markup=menu)
    else:
        await send_msg(message, "max_package", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="← В меню", callback_data="back_to_main")],
        ]))


# ─── Генерация self отчёта ───────────────────────────────────────────────────────

async def _run_self_report(message: Message, user: User, plan: str):
    from src.api import generate_report

    try:
        face_data = json.loads(user.face_json)
        birthdate = user.birth_date.strftime("%d.%m.%Y")

        if user.photo_file_id and "photo_url" not in face_data:
            photo_uri = await _download_photo_data_uri(message.bot, user.photo_file_id)
            if photo_uri:
                face_data["photo_url"] = photo_uri

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

        elif plan == "full":
            palm_left = json.loads(user.palm_left_json) if user.palm_left_json else None
            palm_right = json.loads(user.palm_right_json) if user.palm_right_json else None
            out_blocks: list = []
            html = await loop.run_in_executor(
                None,
                lambda: generate_report(
                    report_type="self",
                    face_data=face_data,
                    name=user.name,
                    birthdate=birthdate,
                    plan="full",
                    palm_data_left=palm_left,
                    palm_data_right=palm_right,
                    reference=user.blocks_json or None,
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
        caption = f"<b>Портрет личности</b> · {_plan_label.get(plan, plan)} готов! ✅"
        filename = f"Портрет личности {_plan_label.get(plan, plan)}.html"
        await _send_report(message, html, caption, plan, "self", filename)

    except Exception as e:
        err_text = MESSAGES["report_error"].text.format(error=html_mod.escape(str(e)))
        await message.answer(err_text, parse_mode="HTML")


# ─── Генерация money отчёта ──────────────────────────────────────────────────────

async def _run_money_report(message: Message, user: User, plan: str):
    from src.api import generate_report

    try:
        face_data = json.loads(user.face_json)
        birthdate = user.birth_date.strftime("%d.%m.%Y")

        if user.photo_file_id and "photo_url" not in face_data:
            photo_uri = await _download_photo_data_uri(message.bot, user.photo_file_id)
            if photo_uri:
                face_data["photo_url"] = photo_uri

        loop = asyncio.get_running_loop()

        if plan == "demo":
            out_blocks: list = []
            html = await loop.run_in_executor(
                None,
                lambda: generate_report(
                    report_type="money",
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
                        db_user.money_blocks_json = json.dumps(out_blocks[0], ensure_ascii=False)
                        await session.commit()

        elif plan == "full":
            palm_left = json.loads(user.palm_left_json) if user.palm_left_json else None
            palm_right = json.loads(user.palm_right_json) if user.palm_right_json else None
            out_blocks: list = []
            html = await loop.run_in_executor(
                None,
                lambda: generate_report(
                    report_type="money",
                    face_data=face_data,
                    name=user.name,
                    birthdate=birthdate,
                    plan="full",
                    palm_data_left=palm_left,
                    palm_data_right=palm_right,
                    reference=user.money_blocks_json or None,
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
                        db_user.money_blocks_json = json.dumps(out_blocks[0], ensure_ascii=False)
                        await session.commit()

        else:
            reference = user.money_blocks_json or None
            html = await loop.run_in_executor(
                None,
                lambda: generate_report(
                    report_type="money",
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
                if db_user and _PLAN_LEVEL.get(plan, 0) > _PLAN_LEVEL.get(db_user.money_plan or "demo", 0):
                    db_user.money_plan = plan
                    db_user.money_html = html
                    await session.commit()

        _plan_label = {"demo": "Демо", "base": "Базовый", "extended": "Расширенный", "full": "Премиум"}
        caption = f"<b>Денежная карта</b> · {_plan_label.get(plan, plan)} готова! ✅"
        filename = f"Денежная карта {_plan_label.get(plan, plan)}.html"
        await _send_report(message, html, caption, plan, "money", filename)

    except Exception as e:
        err_text = MESSAGES["report_error"].text.format(error=html_mod.escape(str(e)))
        await message.answer(err_text, parse_mode="HTML")


# ─── Генерация couple отчёта ─────────────────────────────────────────────────────

async def _run_couple_report(message: Message, user: User, plan: str):
    from src.api import generate_report

    try:
        if not user.partner_name or not user.partner_birth_date:
            await edit_msg(message, "partner_data_missing")
            return

        face_a = json.loads(user.face_json)
        birthdate_a = user.birth_date.strftime("%d.%m.%Y")
        birthdate_b = user.partner_birth_date.strftime("%d.%m.%Y")

        face_b = json.loads(user.partner_face_json) if user.partner_face_json else {}

        if user.photo_file_id and "photo_url" not in face_a:
            photo_uri = await _download_photo_data_uri(message.bot, user.photo_file_id)
            if photo_uri:
                face_a["photo_url"] = photo_uri

        loop = asyncio.get_running_loop()

        if plan == "demo":
            out_blocks: list = []
            html = await loop.run_in_executor(
                None,
                lambda: generate_report(
                    report_type="couple",
                    face_data=face_a,
                    name=user.name,
                    birthdate=birthdate_a,
                    face_data_b=face_b,
                    name_b=user.partner_name,
                    birthdate_b=birthdate_b,
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
                        db_user.couple_blocks_json = json.dumps(out_blocks[0], ensure_ascii=False)
                        await session.commit()
        else:
            reference = user.couple_blocks_json or None
            html = await loop.run_in_executor(
                None,
                lambda: generate_report(
                    report_type="couple",
                    face_data=face_a,
                    name=user.name,
                    birthdate=birthdate_a,
                    face_data_b=face_b,
                    name_b=user.partner_name,
                    birthdate_b=birthdate_b,
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
                if db_user and _PLAN_LEVEL.get(plan, 0) > _PLAN_LEVEL.get(db_user.couple_plan or "demo", 0):
                    db_user.couple_plan = plan
                    db_user.couple_html = html
                    await session.commit()

        _plan_label = {"demo": "Демо", "base": "Базовый", "extended": "Расширенный", "full": "Премиум"}
        caption = f"<b>Совместимость пары</b> · {_plan_label.get(plan, plan)} готова! ✅"
        filename = f"Совместимость {user.name} и {user.partner_name} {_plan_label.get(plan, plan)}.html"
        await _send_report(message, html, caption, plan, "couple", filename)

    except Exception as e:
        err_text = MESSAGES["report_error"].text.format(error=html_mod.escape(str(e)))
        await message.answer(err_text, parse_mode="HTML")
