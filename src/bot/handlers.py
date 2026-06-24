import asyncio
import base64
import html as html_mod
import json
import logging
import secrets
import tempfile
from collections import defaultdict
from datetime import datetime

log = logging.getLogger(__name__)

from aiogram import Router, F
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.types import (
    Message, PhotoSize, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile,
)
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from sqlalchemy import select

from src.bot.config import BOT_USERNAME, ADMIN_IDS
from src.bot.db import async_session, User, Payment
from src.bot.states import RegistrationStates, PalmStates, PartnerStates
from src.bot.messages import send_msg, edit_msg, MESSAGES
from src.bot.services.payment import create_payment, check_payment

router = Router()


# ─── Меню ───────────────────────────────────────────────────────────────────────

def _main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Портрет личности", callback_data="menu_self", icon_custom_emoji_id="5256059072788054036")],
        [InlineKeyboardButton(text="Совместимость пары", callback_data="menu_couple", icon_custom_emoji_id="5256059072788054036")],
        [InlineKeyboardButton(text="Денежная карта",    callback_data="menu_money", icon_custom_emoji_id="5256059072788054036")],
        [InlineKeyboardButton(text="Начать заново",  callback_data="reset_confirm", icon_custom_emoji_id="5339077943056413575")],
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


def _premium_palms_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для премиум-флоу — пропуск или отмена."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пропустить →", callback_data="skip_palms")],
        [InlineKeyboardButton(text="← Отмена", callback_data="back_to_main")],
    ])


def _premium_partner_palms_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для премиум-флоу ладоней партнёра — пропуск или отмена."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пропустить →", callback_data="skip_partner_palms")],
        [InlineKeyboardButton(text="← Отмена", callback_data="back_to_main")],
    ])


def _skip_registration_palms_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пропустить →", callback_data="skip_registration_palms")],
    ])


def _skip_partner_palms_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пропустить →", callback_data="skip_partner_palms")],
        [InlineKeyboardButton(text="← Отмена", callback_data="back_to_main")],
    ])


_PLAN_LEVEL = {"demo": 0, "base": 1, "extended": 2, "full": 3}

# ── Лейблы пакетов (текст берётся из MESSAGES) ──────────────────────────────────
_PACKAGE_NAMES = {"base": "Базовый", "extended": "Расширенный", "full": "Премиум"}

_BASE_PRICES = {"base": 249, "extended": 449, "full": 649}

# Скидки при апгрейде: (текущий_пакет, целевой_пакет) → процент скидки
_UPGRADE_DISCOUNTS = {
    ("base", "extended"): 25,
    ("base", "full"): 25,
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
            if key == "full":
                rows.append([InlineKeyboardButton(text=name, callback_data=f"pkg_{report_prefix}_{key}", icon_custom_emoji_id="5307923023385342441")])
            else:
                rows.append([InlineKeyboardButton(text=name, callback_data=f"pkg_{report_prefix}_{key}", icon_custom_emoji_id="5256191422205280320")])
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
        log.error("Ошибка анализа/сохранения лица для telegram_id=%s", telegram_id, exc_info=True)


async def _analyze_face_return(message: Message, file_id: str, error_msg_key: str = "partner_face_missing") -> dict | None:
    """Скачивает и анализирует лицо.

    При ошибке (лицо не обнаружено или сбой) отправляет пользователю сообщение
    с ключом error_msg_key и возвращает None.
    """
    from src.core.face_analyzer import analyze_face
    import os

    try:
        file = await message.bot.get_file(file_id)
        if not file.file_path:
            await send_msg(message, error_msg_key, reply_markup=_cancel_keyboard())
            return None
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            await message.bot.download_file(file.file_path, tmp.name)
            tmp_path = tmp.name
        try:
            loop = asyncio.get_running_loop()
            face_data = await loop.run_in_executor(None, lambda: analyze_face(tmp_path))
        finally:
            os.unlink(tmp_path)
        return face_data
    except Exception:
        log.error("Ошибка анализа лица (file_id=%s)", file_id, exc_info=True)
        await send_msg(message, error_msg_key, reply_markup=_cancel_keyboard())
        return None


# ─── /start ────────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, command: CommandObject):
    user = await get_user(message.from_user.id)
    if user:
        await state.clear()
        if _is_complete(user):
            await send_msg(message, "choose_section", reply_markup=_main_menu())
        elif not user.name:
            await send_msg(message, "start_returning_no_name")
            await state.set_state(RegistrationStates.waiting_for_name)
        elif not user.face_json:
            await send_msg(message, "start_returning_no_photo", name=user.name)
            await state.set_state(RegistrationStates.waiting_for_photo)
        elif not user.birth_date:
            await send_msg(message, "start_returning_no_birthdate", name=user.name)
            await state.set_state(RegistrationStates.waiting_for_birth_date)
        return

    ref_arg = command.args  # deep link payload, e.g. /start REF_CODE
    ref_code = secrets.token_urlsafe(6)  # unique code for this new user

    async with async_session() as session:
        referred_by = None
        if ref_arg:
            res = await session.execute(select(User).where(User.referral_code == ref_arg))
            referrer = res.scalar_one_or_none()
            if referrer and referrer.telegram_id != message.from_user.id:
                referred_by = ref_arg

        new_user = User(
            telegram_id=message.from_user.id,
            referral_code=ref_code,
            referred_by=referred_by,
        )
        session.add(new_user)
        await session.commit()

    await send_msg(message, "start_new")
    await state.set_state(RegistrationStates.waiting_for_name)


# ─── Регистрация ────────────────────────────────────────────────────────────────

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

    await send_msg(message, "photo_received")
    await state.set_state(RegistrationStates.waiting_for_photo)


@router.message(RegistrationStates.waiting_for_name)
async def process_name_invalid(message: Message):
    await send_msg(message, "name_invalid")


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

    await send_msg(message, "name_saved")
    await state.set_state(RegistrationStates.waiting_for_birth_date)


@router.message(RegistrationStates.waiting_for_photo)
async def process_photo_invalid(message: Message):
    await send_msg(message, "photo_invalid")


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

    await state.set_state(RegistrationStates.waiting_for_palm_left)
    await send_msg(message, "registration_palm_request", reply_markup=_skip_registration_palms_keyboard())


@router.message(RegistrationStates.waiting_for_birth_date)
async def process_birth_date_invalid(message: Message):
    await send_msg(message, "birthdate_invalid_type")


# ─── Ладони при регистрации ────────────────────────────────────────────────────

@router.message(RegistrationStates.waiting_for_palm_left, F.photo)
async def process_reg_palm_left(message: Message, state: FSMContext):
    photo: PhotoSize = message.photo[-1]
    processing_msg = await send_msg(message, "palm_left_analyzing")

    palm_data = await _download_and_analyze_palm(message.bot, photo.file_id)

    if not palm_data:
        try:
            await processing_msg.delete()
        except TelegramBadRequest:
            pass
        await send_msg(message, "palm_not_detected", reply_markup=_skip_registration_palms_keyboard())
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
    await state.set_state(RegistrationStates.waiting_for_palm_right)
    await send_msg(message, "registration_palm_left_done", reply_markup=_skip_registration_palms_keyboard())


@router.message(RegistrationStates.waiting_for_palm_left)
async def process_reg_palm_left_invalid(message: Message):
    await send_msg(message, "palm_photo_invalid", reply_markup=_skip_registration_palms_keyboard())


@router.message(RegistrationStates.waiting_for_palm_right, F.photo)
async def process_reg_palm_right(message: Message, state: FSMContext):
    photo: PhotoSize = message.photo[-1]
    processing_msg = await send_msg(message, "palm_right_analyzing")

    palm_data = await _download_and_analyze_palm(message.bot, photo.file_id)

    if not palm_data:
        try:
            await processing_msg.delete()
        except TelegramBadRequest:
            pass
        await send_msg(message, "palm_not_detected", reply_markup=_skip_registration_palms_keyboard())
        return

    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        if user:
            user.palm_right_json = json.dumps(palm_data, ensure_ascii=False)
            await session.commit()

    try:
        await processing_msg.delete()
    except TelegramBadRequest:
        pass

    await state.clear()
    await send_msg(message, "registration_palm_done")
    await send_msg(message, "choose_section", reply_markup=_main_menu())


@router.message(RegistrationStates.waiting_for_palm_right)
async def process_reg_palm_right_invalid(message: Message):
    await send_msg(message, "palm_photo_invalid", reply_markup=_skip_registration_palms_keyboard())


# ─── Главное меню ───────────────────────────────────────────────────────────────

async def _edit_to_packages(message: Message, user: User, report_prefix: str):
    plan_field = {"self": "purchased_plan", "money": "money_plan", "couple": "couple_plan"}[report_prefix]
    purchased = getattr(user, plan_field, None) or "demo"
    menu = _packages_menu(above_plan=purchased, report_prefix=report_prefix)
    if menu.inline_keyboard[:-1]:
        pkg_msg_key = {"self": "choose_package_self", "money": "choose_package_money", "couple": "choose_package_couple"}[report_prefix]
        await edit_msg(message, pkg_msg_key, reply_markup=menu)
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
                [InlineKeyboardButton(text="Запустить анализ", callback_data="start_couple_demo")],
                [InlineKeyboardButton(text="← В меню", callback_data="back_to_main")],
            ]),
        )
    await callback.answer()


# ─── Пакеты ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "back_to_main")
async def cb_back_to_main(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.clear()

    # Если были в процессе сбора ладоней — возвращаем к пакетам, а не в главное меню
    pending_report = data.get("pending_report_type")
    if pending_report:
        user = await get_user(callback.from_user.id)
        if user:
            try:
                await _edit_to_packages(callback.message, user, pending_report)
            except Exception:
                await send_msg(callback.message, "choose_section", reply_markup=_main_menu())
            await callback.answer()
            return

    try:
        await edit_msg(callback.message, "choose_section", reply_markup=_main_menu())
    except Exception:
        await send_msg(callback.message, "choose_section", reply_markup=_main_menu())
    await callback.answer()


@router.callback_query(F.data == "skip_palms")
async def cb_skip_palms(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.clear()

    user = await get_user(callback.from_user.id)
    pending_plan = data.get("pending_plan", "full")
    report_type = data.get("pending_report_type", "self")
    need_partner_palms = data.get("need_partner_palms", False)

    # Для couple full — после пропуска своих ладоней запрашиваем ладони партнёра
    if report_type == "couple" and need_partner_palms:
        await state.set_state(PartnerStates.waiting_for_partner_palm_left)
        await state.update_data(pending_plan=pending_plan, pending_report_type=report_type)
        try:
            await callback.message.delete()
        except TelegramBadRequest:
            pass
        await send_msg(callback.message, "partner_palm_needed_premium", reply_markup=_skip_partner_palms_keyboard())
        await callback.answer()
        return

    # После сбора/пропуска ладоней — создаём платёж
    await _create_payment_and_show(callback, user, report_type, pending_plan)
    await callback.answer()


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
            if callback.message.photo:
                await callback.message.edit_caption(caption=text, reply_markup=markup, parse_mode="HTML")
            else:
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
            [InlineKeyboardButton(text="← Отмена", callback_data="back_to_main")],
        ]),
    )


@router.message(PartnerStates.waiting_for_partner_birthdate)
async def process_partner_birthdate_invalid(message: Message):
    await send_msg(message, "partner_birthdate_invalid_type", reply_markup=_cancel_keyboard())


@router.message(PartnerStates.waiting_for_partner_photo, F.photo)
async def process_partner_photo(message: Message, state: FSMContext):
    photo: PhotoSize = message.photo[-1]
    processing_msg = await send_msg(message, "analyzing")

    face_data = await _analyze_face_return(message, photo.file_id, error_msg_key="partner_face_missing")

    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        if user:
            user.partner_photo_file_id = photo.file_id
            if face_data:
                user.partner_face_json = json.dumps(face_data, ensure_ascii=False)
            await session.commit()

    try:
        await processing_msg.delete()
    except TelegramBadRequest:
        pass

    if not face_data:
        return

    # После фото партнёра — запрашиваем ладони партнёра
    await state.set_state(PartnerStates.waiting_for_partner_palm_left)
    await send_msg(message, "partner_palm_request", reply_markup=_skip_partner_palms_keyboard())


@router.message(PartnerStates.waiting_for_partner_photo)
async def process_partner_photo_invalid(message: Message):
    await send_msg(
        message, "partner_photo_invalid",
        reply_markup=_cancel_keyboard(),
    )


# ─── Ладони партнёра (FSM для couple) ──────────────────────────────────────────

def _partner_palms_kb(state_data: dict) -> InlineKeyboardMarkup:
    """Клавиатура для ладоней партнёра (с пропуском в любом флоу)."""
    if state_data.get("pending_plan"):
        return _premium_partner_palms_keyboard()
    return _skip_partner_palms_keyboard()


@router.message(PartnerStates.waiting_for_partner_palm_left, F.photo)
async def process_partner_palm_left(message: Message, state: FSMContext):
    photo: PhotoSize = message.photo[-1]
    processing_msg = await send_msg(message, "palm_left_analyzing")

    palm_data = await _download_and_analyze_palm(message.bot, photo.file_id)
    state_data = await state.get_data()

    if not palm_data:
        try:
            await processing_msg.delete()
        except TelegramBadRequest:
            pass
        await send_msg(message, "palm_not_detected", reply_markup=_partner_palms_kb(state_data))
        return

    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        if user:
            user.partner_palm_left_json = json.dumps(palm_data, ensure_ascii=False)
            await session.commit()

    try:
        await processing_msg.delete()
    except TelegramBadRequest:
        pass
    await state.set_state(PartnerStates.waiting_for_partner_palm_right)
    await send_msg(message, "partner_palm_left_done", reply_markup=_partner_palms_kb(state_data))


@router.message(PartnerStates.waiting_for_partner_palm_left)
async def process_partner_palm_left_invalid(message: Message, state: FSMContext):
    state_data = await state.get_data()
    await send_msg(message, "palm_photo_invalid", reply_markup=_partner_palms_kb(state_data))


@router.message(PartnerStates.waiting_for_partner_palm_right, F.photo)
async def process_partner_palm_right(message: Message, state: FSMContext):
    photo: PhotoSize = message.photo[-1]
    processing_msg = await send_msg(message, "palm_right_analyzing")

    palm_data = await _download_and_analyze_palm(message.bot, photo.file_id)

    if not palm_data:
        try:
            await processing_msg.delete()
        except TelegramBadRequest:
            pass
        state_data = await state.get_data()
        await send_msg(message, "palm_not_detected", reply_markup=_partner_palms_kb(state_data))
        return

    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        if user:
            user.partner_palm_right_json = json.dumps(palm_data, ensure_ascii=False)
            await session.commit()

    try:
        await processing_msg.delete()
    except TelegramBadRequest:
        pass

    data = await state.get_data()
    await state.clear()

    user = await get_user(message.from_user.id)

    # Если это премиум-флоу — создаём платёж
    pending_plan = data.get("pending_plan")
    if pending_plan:
        await _create_payment_and_show(message, user, "couple", pending_plan)
    else:
        status_msg = await send_msg(message, "partner_data_received")
        asyncio.create_task(_run_couple_report(status_msg, user, "demo"))


@router.message(PartnerStates.waiting_for_partner_palm_right)
async def process_partner_palm_right_invalid(message: Message, state: FSMContext):
    state_data = await state.get_data()
    await send_msg(message, "palm_photo_invalid", reply_markup=_partner_palms_kb(state_data))


@router.callback_query(F.data == "skip_partner_palms")
async def cb_skip_partner_palms(callback: CallbackQuery, state: FSMContext):
    """Пропуск ладоней партнёра."""
    data = await state.get_data()
    await state.clear()

    user = await get_user(callback.from_user.id)
    pending_plan = data.get("pending_plan")

    # Если это премиум-флоу — создаём платёж (сообщение НЕ удаляем,
    # т.к. _create_payment_and_show редактирует его для показа кнопки оплаты)
    if pending_plan:
        await _create_payment_and_show(callback, user, "couple", pending_plan)
    else:
        try:
            await callback.message.delete()
        except TelegramBadRequest:
            pass
        status_msg = await send_msg(callback.message, "partner_data_received")
        asyncio.create_task(_run_couple_report(status_msg, user, "demo"))
    await callback.answer()


@router.callback_query(F.data == "skip_registration_palms")
async def cb_skip_registration_palms(callback: CallbackQuery, state: FSMContext):
    """Пропуск ладоней при регистрации — переход в главное меню."""
    await state.clear()
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass
    await send_msg(callback.message, "registration_palm_skipped")
    await send_msg(callback.message, "choose_section", reply_markup=_main_menu())
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


@router.callback_query(F.data == "start_couple_demo")
async def cb_start_couple_demo(callback: CallbackQuery, state: FSMContext):
    """Начинает сбор данных партнёра для анализа совместимости."""
    await state.set_state(PartnerStates.waiting_for_partner_name)
    await edit_msg(
        callback.message, "partner_name_prompt",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="← Отмена", callback_data="back_to_main")],
        ]),
    )
    await callback.answer()


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

    # Для full-пакетов нужна проверка ладоней — спрашиваем до оплаты (с возможностью пропуска)
    if plan_key == "full" and report_prefix in ("self", "money"):
        has_both_palms = bool(user.palm_left_json and user.palm_right_json)
        if not has_both_palms:
            await state.set_state(PalmStates.waiting_for_palm_left)
            await state.update_data(pending_plan=plan_key, pending_report_type=report_prefix)
            await edit_msg(
                callback.message, "palm_needed_self" if report_prefix == "self" else "palm_needed_money",
                reply_markup=_premium_palms_keyboard(),
            )
            await callback.answer()
            return

    # Для couple full — проверяем ладони пользователя и партнёра (с возможностью пропуска)
    if plan_key == "full" and report_prefix == "couple":
        has_user_palms = bool(user.palm_left_json and user.palm_right_json)
        has_partner_palms = bool(user.partner_palm_left_json and user.partner_palm_right_json)
        if not has_user_palms:
            await state.set_state(PalmStates.waiting_for_palm_left)
            await state.update_data(pending_plan=plan_key, pending_report_type=report_prefix, need_partner_palms=not has_partner_palms)
            await edit_msg(callback.message, "palm_needed_couple", reply_markup=_premium_palms_keyboard())
            await callback.answer()
            return
        if not has_partner_palms:
            await state.set_state(PartnerStates.waiting_for_partner_palm_left)
            await state.update_data(pending_plan=plan_key, pending_report_type=report_prefix)
            await edit_msg(callback.message, "partner_palm_needed_premium", reply_markup=_premium_partner_palms_keyboard())
            await callback.answer()
            return

    # Создаём платёж через общий хелпер
    await _create_payment_and_show(callback, user, report_prefix, plan_key)
    await callback.answer()


@router.callback_query(F.data.startswith("check_"))
async def cb_check_payment(callback: CallbackQuery, state: FSMContext):
    """Проверка статуса оплаты и запуск отчёта при успехе."""
    payment_id = callback.data.removeprefix("check_")

    async with async_session() as session:
        result = await session.execute(
            select(Payment).where(Payment.yookassa_id == payment_id)
        )
        payment_record = result.scalar_one_or_none()

    if not payment_record:
        await callback.answer("Платёж не найден", show_alert=True)
        return

    if payment_record.status == "succeeded":
        await callback.answer("Оплата подтверждена! ✅", show_alert=False)
        # Обновляем сообщение — убираем кнопки оплаты
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass

        user = await get_user(callback.from_user.id)
        if not user:
            await callback.answer()
            return

        report_prefix = payment_record.report_type
        plan_key = payment_record.plan
        status_msg = await edit_msg(callback.message, "analyzing")

        if report_prefix == "self":
            asyncio.create_task(_run_self_report(status_msg, user, plan_key))
        elif report_prefix == "money":
            asyncio.create_task(_run_money_report(status_msg, user, plan_key))
        elif report_prefix == "couple":
            asyncio.create_task(_run_couple_report(status_msg, user, plan_key))
        return

    # Проверяем актуальный статус через YooKassa API
    try:
        yoo_payment = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: check_payment(payment_id),
        )
    except Exception as exc:
        log.error("Ошибка проверки платежа %s: %s", payment_id, exc, exc_info=True)
        await callback.answer(f"Ошибка проверки: {exc}", show_alert=True)
        return

    new_status = yoo_payment.status

    # Обновляем статус в БД
    async with async_session() as session:
        result = await session.execute(
            select(Payment).where(Payment.yookassa_id == payment_id)
        )
        payment_record = result.scalar_one_or_none()
        if payment_record:
            payment_record.status = new_status
            await session.commit()

    if new_status == "succeeded":
        await callback.answer("Оплата подтверждена! ✅", show_alert=False)
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass

        user = await get_user(callback.from_user.id)
        if not user:
            await callback.answer()
            return

        report_prefix = payment_record.report_type
        plan_key = payment_record.plan
        status_msg = await edit_msg(callback.message, "analyzing")

        if report_prefix == "self":
            asyncio.create_task(_run_self_report(status_msg, user, plan_key))
        elif report_prefix == "money":
            asyncio.create_task(_run_money_report(status_msg, user, plan_key))
        elif report_prefix == "couple":
            asyncio.create_task(_run_couple_report(status_msg, user, plan_key))
    elif new_status == "canceled":
        await callback.answer("Платёж отменён ❌", show_alert=True)
        try:
            await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="← В меню", callback_data="back_to_main")],
            ]))
        except TelegramBadRequest:
            pass
    else:
        # pending_waiting_for_capture / pending и др.
        await callback.answer("Платёж ещё не завершён, попробуйте чуть позже", show_alert=True)


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
                reply_markup=_premium_palms_keyboard(),
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
        log.error("Ошибка анализа ладони (file_id=%s)", file_id, exc_info=True)
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
        await send_msg(message, "palm_not_detected", reply_markup=_premium_palms_keyboard())
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
    await send_msg(message, "palm_left_accepted", reply_markup=_premium_palms_keyboard())


@router.message(PalmStates.waiting_for_palm_left)
async def process_palm_left_invalid(message: Message):
    await send_msg(message, "palm_photo_invalid", reply_markup=_premium_palms_keyboard())


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
        await send_msg(message, "palm_not_detected", reply_markup=_premium_palms_keyboard())
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

    pending_plan = data.get("pending_plan", "full")
    report_type = data.get("pending_report_type", "self")
    need_partner_palms = data.get("need_partner_palms", False)

    # Для couple full — после своих ладоней запрашиваем ладони партнёра
    if report_type == "couple" and need_partner_palms:
        await state.set_state(PartnerStates.waiting_for_partner_palm_left)
        await state.update_data(pending_plan=pending_plan, pending_report_type=report_type)
        await send_msg(message, "partner_palm_needed_premium", reply_markup=_premium_partner_palms_keyboard())
        return

    # Ладони собраны — создаём платёж
    await _create_payment_and_show(message, user, report_type, pending_plan)


@router.message(PalmStates.waiting_for_palm_right)
async def process_palm_right_invalid(message: Message):
    await send_msg(message, "palm_photo_invalid", reply_markup=_premium_palms_keyboard())


# ─── Хелпер создания платежа ────────────────────────────────────────────────────

def _payment_keyboard(yoo_payment_id: str, confirmation_url: str) -> InlineKeyboardMarkup:
    """Клавиатура для оплаты YooKassa — единая для всех флоу."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Перейти к оплате", url=confirmation_url, icon_custom_emoji_id="5337238593247131255")],
        [InlineKeyboardButton(text="Я оплатил", callback_data=f"check_{yoo_payment_id}", icon_custom_emoji_id="5206607081334906820")],
        [InlineKeyboardButton(text="← Отмена", callback_data="back_to_main")],
    ])


async def _create_payment_and_show(callback_or_msg, user: User, report_type: str, plan_key: str):
    """Создаёт платёж YooKassa и показывает кнопку оплаты."""
    try:
        plan_field = {"self": "purchased_plan", "money": "money_plan", "couple": "couple_plan"}[report_type]
        current_plan = getattr(user, plan_field, None) or "demo"
        price = _get_discounted_price(current_plan, plan_key)
        amount_str = f"{price}.00"

        yoo_payment = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: create_payment(report_type, plan_key, user.telegram_id, amount=amount_str),
        )

        async with async_session() as session:
            payment_record = Payment(
                yookassa_id=yoo_payment.id,
                telegram_id=user.telegram_id,
                report_type=report_type,
                plan=plan_key,
                amount=amount_str,
                status=yoo_payment.status,
                confirmation_url=yoo_payment.confirmation.confirmation_url,
            )
            session.add(payment_record)
            await session.commit()

        confirmation_url = yoo_payment.confirmation.confirmation_url

        _plan_label = {"base": "Базовый", "extended": "Расширенный", "full": "Премиум"}
        _report_label = {"self": "Портрет личности", "money": "Денежная карта", "couple": "Совместимость пары"}

        text = MESSAGES["payment_created"].text.format(
            report=_report_label.get(report_type, ""),
            plan=_plan_label.get(plan_key, ""),
            price=price,
        )

        markup = _payment_keyboard(yoo_payment.id, confirmation_url)

        if isinstance(callback_or_msg, CallbackQuery):
            msg = callback_or_msg.message
            try:
                if msg.photo:
                    await msg.edit_caption(caption=text, reply_markup=markup, parse_mode="HTML")
                else:
                    await msg.edit_text(text=text, reply_markup=markup, parse_mode="HTML")
            except TelegramBadRequest:
                # Сообщение могло быть удалено/устареть — отправляем новое
                await msg.answer(text=text, reply_markup=markup, parse_mode="HTML")
        else:
            await callback_or_msg.answer(text=text, reply_markup=markup, parse_mode="HTML")

    except Exception as e:
        log.error("Ошибка создания платежа (_create_payment_and_show): %s", e, exc_info=True)
        err_text = MESSAGES["payment_create_error"].text.format(error=str(e))
        if isinstance(callback_or_msg, CallbackQuery):
            msg = callback_or_msg.message
            try:
                if msg.photo:
                    await msg.edit_caption(caption=err_text, parse_mode="HTML")
                else:
                    await msg.edit_text(text=err_text, parse_mode="HTML")
            except TelegramBadRequest:
                await msg.answer(text=err_text, parse_mode="HTML")
        else:
            await callback_or_msg.answer(text=err_text, parse_mode="HTML")


# ─── Вспомогательные ────────────────────────────────────────────────────────────

async def _download_photo_data_uri(bot, file_id: str) -> str | None:
    try:
        file = await bot.get_file(file_id)
        buf = await bot.download_file(file.file_path)
        data = base64.b64encode(buf.read()).decode("ascii")
        return f"data:image/jpeg;base64,{data}"
    except Exception:
        log.error("Ошибка загрузки фото (file_id=%s)", file_id, exc_info=True)
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
        pkg_msg_key = {"self": "choose_package_self", "money": "choose_package_money", "couple": "choose_package_couple"}[report_prefix]
        await send_msg(message, pkg_msg_key, reply_markup=menu)
    else:
        await send_msg(message, "max_package", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="← В меню", callback_data="back_to_main")],
        ]))


# ─── Генерация self отчёта ───────────────────────────────────────────────────────

async def _run_self_report(message: Message, user: User, plan: str):
    from src.api import generate_report

    log.info("Запуск self отчёта: telegram_id=%s, plan=%s", user.telegram_id, plan)
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
        caption = f"<b>Портрет личности</b> · {_plan_label.get(plan, plan)} готов! <tg-emoji emoji-id=\"5337019240677388490\">📚</tg-emoji>"
        filename = f"Портрет личности {_plan_label.get(plan, plan)}.html"
        await _send_report(message, html, caption, plan, "self", filename)

    except Exception as e:
        log.error("Ошибка генерации self отчёта: telegram_id=%s, plan=%s",
                  user.telegram_id, plan, exc_info=True)
        err_text = MESSAGES["report_error"].text.format(error=html_mod.escape(str(e)))
        await message.answer(err_text, parse_mode="HTML")


# ─── Генерация money отчёта ──────────────────────────────────────────────────────

async def _run_money_report(message: Message, user: User, plan: str):
    from src.api import generate_report

    log.info("Запуск money отчёта: telegram_id=%s, plan=%s", user.telegram_id, plan)
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
        caption = f"<b>Денежная карта</b> · {_plan_label.get(plan, plan)} готова! <tg-emoji emoji-id=\"5337019240677388490\">📚</tg-emoji>"
        filename = f"Денежная карта {_plan_label.get(plan, plan)}.html"
        await _send_report(message, html, caption, plan, "money", filename)

    except Exception as e:
        log.error("Ошибка генерации money отчёта: telegram_id=%s, plan=%s",
                  user.telegram_id, plan, exc_info=True)
        err_text = MESSAGES["report_error"].text.format(error=html_mod.escape(str(e)))
        await message.answer(err_text, parse_mode="HTML")


# ─── Генерация couple отчёта ─────────────────────────────────────────────────────

async def _run_couple_report(message: Message, user: User, plan: str):
    from src.api import generate_report

    log.info("Запуск couple отчёта: telegram_id=%s, plan=%s", user.telegram_id, plan)
    try:
        if not user.partner_name or not user.partner_birth_date:
            await edit_msg(message, "partner_data_missing")
            return

        face_a = json.loads(user.face_json)
        birthdate_a = user.birth_date.strftime("%d.%m.%Y")
        birthdate_b = user.partner_birth_date.strftime("%d.%m.%Y")

        face_b = json.loads(user.partner_face_json) if user.partner_face_json else {}

        if not face_b.get("proportions"):
            await edit_msg(message, "partner_face_missing")
            return

        if user.photo_file_id and "photo_url" not in face_a:
            photo_uri = await _download_photo_data_uri(message.bot, user.photo_file_id)
            if photo_uri:
                face_a["photo_url"] = photo_uri

        if user.partner_photo_file_id and "photo_url" not in face_b:
            photo_uri = await _download_photo_data_uri(message.bot, user.partner_photo_file_id)
            if photo_uri:
                face_b["photo_url"] = photo_uri

        # Данные ладоней
        palm_a_left = json.loads(user.palm_left_json) if user.palm_left_json else None
        palm_a_right = json.loads(user.palm_right_json) if user.palm_right_json else None
        palm_b_left = json.loads(user.partner_palm_left_json) if user.partner_palm_left_json else None
        palm_b_right = json.loads(user.partner_palm_right_json) if user.partner_palm_right_json else None

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
                    palm_data_left=palm_a_left,
                    palm_data_right=palm_a_right,
                    palm_data_b_left=palm_b_left,
                    palm_data_b_right=palm_b_right,
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
                    palm_data_left=palm_a_left,
                    palm_data_right=palm_a_right,
                    palm_data_b_left=palm_b_left,
                    palm_data_b_right=palm_b_right,
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
        caption = f"<b>Совместимость пары</b> · {_plan_label.get(plan, plan)} готова! <tg-emoji emoji-id=\"5337019240677388490\">📚</tg-emoji>"
        filename = f"Совместимость {user.name} и {user.partner_name} {_plan_label.get(plan, plan)}.html"
        await _send_report(message, html, caption, plan, "couple", filename)

    except Exception as e:
        log.error("Ошибка генерации couple отчёта: telegram_id=%s, plan=%s",
                  user.telegram_id, plan, exc_info=True)
        err_text = MESSAGES["report_error"].text.format(error=html_mod.escape(str(e)))
        await message.answer(err_text, parse_mode="HTML")


# ─── Реферальные команды ─────────────────────────────────────────────────────────

@router.message(Command("reflink"))
async def cmd_reflink(message: Message):
    """Выдаёт пользователю его реферальную ссылку."""
    if not BOT_USERNAME:
        await message.answer(
            "⚠️ Реферальная система не настроена — добавьте <code>BOT_USERNAME</code> в .env",
            parse_mode="HTML",
        )
        return

    user = await get_user(message.from_user.id)
    if not user:
        await send_msg(message, "start_new")
        return

    ref_code = user.referral_code
    if not ref_code:
        ref_code = secrets.token_urlsafe(6)
        async with async_session() as session:
            res = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
            u = res.scalar_one_or_none()
            if u:
                u.referral_code = ref_code
                await session.commit()

    link = f"https://t.me/{BOT_USERNAME}?start={ref_code}"
    await message.answer(
        f"<b>Ваша реферальная ссылка:</b>\n\n"
        f"<code>{link}</code>\n\n"
        f"Поделитесь ею с друзьями — бот покажет, сколько человек зарегистрировалось по вашей ссылке.",
        parse_mode="HTML",
    )


@router.message(Command("refstats"))
async def cmd_refstats(message: Message):
    """Статистика реферальных ссылок (только для администраторов)."""
    if ADMIN_IDS and message.from_user.id not in ADMIN_IDS:
        return

    async with async_session() as session:
        res_users = await session.execute(
            select(User).where(User.referral_code.isnot(None))
        )
        all_users = res_users.scalars().all()

        res_referred = await session.execute(
            select(User).where(User.referred_by.isnot(None))
        )
        referred_users = res_referred.scalars().all()

        code_to_tids: dict[str, list[int]] = defaultdict(list)
        for ru in referred_users:
            code_to_tids[ru.referred_by].append(ru.telegram_id)

        referred_tids = [ru.telegram_id for ru in referred_users]
        if referred_tids:
            res_pay = await session.execute(
                select(Payment).where(
                    Payment.telegram_id.in_(referred_tids),
                    Payment.status == "succeeded",
                )
            )
            all_payments = res_pay.scalars().all()
        else:
            all_payments = []

    tid_to_payments: dict[int, list] = defaultdict(list)
    for p in all_payments:
        tid_to_payments[p.telegram_id].append(p)

    active: list[tuple] = [
        (u, code_to_tids[u.referral_code])
        for u in all_users
        if code_to_tids.get(u.referral_code)
    ]

    if not active:
        await message.answer(
            "<b>Реферальная статистика</b>\n\nПока никто не пришёл по реферальным ссылкам.",
            parse_mode="HTML",
        )
        return

    active.sort(key=lambda x: -len(x[1]))

    lines = ["<b>Реферальная статистика</b>\n"]
    for user, tids in active:
        payments = [p for tid in tids for p in tid_to_payments.get(tid, [])]
        total_amount = sum(float(p.amount) for p in payments)
        name = user.name or "—"
        lines.append(
            f"👤 <b>{name}</b> (id: <code>{user.telegram_id}</code>)\n"
            f"   Код: <code>{user.referral_code}</code>\n"
            f"   Приглашено: {len(tids)} чел.\n"
            f"   Платежей: {len(payments)} · {total_amount:.0f} ₽\n"
        )

    total_referred = len(referred_users)
    total_paid = sum(float(p.amount) for p in all_payments)
    lines.append(f"\n<b>Итого:</b> {total_referred} реф. пользователей · {total_paid:.0f} ₽")

    await message.answer("\n".join(lines), parse_mode="HTML")


# ─── Сброс данных ────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "reset_confirm")
async def cb_reset_confirm(callback: CallbackQuery, state: FSMContext):
    """Показывает экран подтверждения сброса."""
    await state.clear()
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Да, сбросить", callback_data="reset_execute", icon_custom_emoji_id="5447644880824181073")],
        [InlineKeyboardButton(text="← Отмена", callback_data="back_to_main")],
    ])
    try:
        await edit_msg(callback.message, "reset_confirm", reply_markup=markup)
    except Exception:
        await send_msg(callback.message, "reset_confirm", reply_markup=markup)
    await callback.answer()


@router.callback_query(F.data == "reset_execute")
async def cb_reset_execute(callback: CallbackQuery, state: FSMContext):
    """Сбрасывает результаты отчётов и запускает регистрацию заново."""
    await state.clear()

    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result.scalar_one_or_none()
        if user:
            # Сбрасываем все результаты отчётов, данные ладоней и партнёра
            user.face_json = None
            user.palm_left_json = None
            user.palm_right_json = None
            user.blocks_json = None
            user.purchased_plan = None
            user.report_html = None
            user.money_blocks_json = None
            user.money_plan = None
            user.money_html = None
            user.partner_name = None
            user.partner_birth_date = None
            user.partner_photo_file_id = None
            user.partner_face_json = None
            user.partner_palm_left_json = None
            user.partner_palm_right_json = None
            user.couple_blocks_json = None
            user.couple_plan = None
            user.couple_html = None
            # Сбрасываем базовые данные профиля для полной перерегистрации
            user.name = None
            user.photo_file_id = None
            user.birth_date = None
            await session.commit()

    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass

    await send_msg(callback.message, "reset_done")
    await send_msg(callback.message, "start_new")
    await state.set_state(RegistrationStates.waiting_for_name)
    await callback.answer()
