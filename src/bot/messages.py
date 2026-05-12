"""Централизованная конфигурация сообщений бота.

Каждое сообщение описано в одном месте — текст и опциональная картинка.
Для изменения текста или добавления/удаления картинки достаточно изменить MESSAGES.

Структура:
- MessageConfig — конфигурация одного сообщения (текст + опциональная картинка)
- MESSAGES — словарь всех сообщений бота
- send_msg() — отправка сообщения с учётом конфигурации
- edit_msg() — редактирование сообщения с учётом конфигурации
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from html import escape as _html_escape

from aiogram.types import Message, FSInputFile, InputMediaPhoto
from aiogram.exceptions import TelegramBadRequest

# Базовая директория для медиафайлов бота
MEDIA_DIR = Path(__file__).parent / "media"


@dataclass
class MessageConfig:
    """Конфигурация одного сообщения бота.

    Attributes:
        key: Уникальный идентификатор сообщения
        text: Текст сообщения (поддерживает {placeholders} для format())
        photo: Имя файла картинки из директории media/ (или None)
    """
    key: str
    text: str
    photo: Optional[str] = None  # имя файла из MEDIA_DIR или None

    @property
    def photo_path(self) -> Optional[Path]:
        """Полный путь к файлу картинки или None."""
        if self.photo:
            path = MEDIA_DIR / self.photo
            return path if path.exists() else None
        return None


# ─── Все сообщения бота ────────────────────────────────────────────────────────
# Чтобы добавить картинку к сообщению, просто укажи имя файла в поле photo.
# Файл должен лежать в директории src/bot/media/.

MESSAGES: dict[str, MessageConfig] = {

    # ── Регистрация ───────────────────────────────────────────────────────────
    "start_new": MessageConfig(
        key="start_new",
        text=(
            "<b>Я могу проанализировать:</b>\n\n"
            "<tg-emoji emoji-id=\"5359794223887443699\">◀️</tg-emoji> твою личность\n"
            "<tg-emoji emoji-id=\"5359794223887443699\">◀️</tg-emoji> совместимость с партнером\n"
            "<tg-emoji emoji-id=\"5359794223887443699\">◀️</tg-emoji> денежный потенциал\n\n"
            "<b>Для начала, напиши свое имя</b> <tg-emoji emoji-id=\"5348460861755262251\">✍️</tg-emoji>"
        ),
    ),
    "start_returning_incomplete": MessageConfig(
        key="start_returning_incomplete",
        text="С возвращением, <b>{name}</b>! <tg-emoji emoji-id=\"5237948187838262194\">👁️</tg-emoji>",
    ),
    "photo_received": MessageConfig(
        key="photo_received",
        text=(
            "<tg-emoji emoji-id=\"5379965177015846816\">🔑</tg-emoji> <b>Твоё фото - это ключ к разбору</b>\n\n"
            "<b>Важные моменты:</b>\n"
            "<tg-emoji emoji-id=\"5359794223887443699\">◀️</tg-emoji> Загрузи всего 1 фото\n"
            "<tg-emoji emoji-id=\"5359794223887443699\">◀️</tg-emoji> Используй крупный план своего лица/селфи\n"
            "<tg-emoji emoji-id=\"5359794223887443699\">◀️</tg-emoji> Не используй фото с резкими эмоциями, максимум легкая улыбка\n"
            "<tg-emoji emoji-id=\"5359794223887443699\">◀️</tg-emoji> Прямая поза без наклонов головы и шеи\n"
            "<tg-emoji emoji-id=\"5359794223887443699\">◀️</tg-emoji> Хорошее освещение = качественный результат"
        ),
    ),
    "photo_invalid": MessageConfig(
        key="photo_invalid",
        text="Пожалуйста, пришли именно <b>фото</b> <tg-emoji emoji-id=\"5395698544164233115\">🤩</tg-emoji>",
    ),
    "name_empty": MessageConfig(
        key="name_empty",
        text="Имя не может быть пустым. Попробуй ещё раз <tg-emoji emoji-id=\"5348460861755262251\">✍️</tg-emoji> ",
    ),
    "name_saved": MessageConfig(
        key="name_saved",
        text=(
            "<b>Запомнил!</b> <tg-emoji emoji-id=\"5348460861755262251\">✍️</tg-emoji>\n"
            "Отправь дату рождения в формате <b>ДД.ММ.ГГГГ</b> <tg-emoji emoji-id=\"5203934104143294160\">🔏</tg-emoji>\n"
            "Она нужна для глубокого анализа личности"
        ),
    ),
    "name_invalid": MessageConfig(
        key="name_invalid",
        text="Пожалуйста, напиши имя текстом <tg-emoji emoji-id=\"5348460861755262251\">✍️</tg-emoji>",
    ),
    "birthdate_invalid": MessageConfig(
        key="birthdate_invalid",
        text="Неверный формат. Напиши дату в формате <b>ДД.ММ.ГГГГ</b>, например <code>15.06.1990</code> <tg-emoji emoji-id=\"5203934104143294160\">🔏</tg-emoji>",
    ),
    "birthdate_invalid_type": MessageConfig(
        key="birthdate_invalid_type",
        text="Пожалуйста, напиши дату текстом в формате <b>ДД.ММ.ГГГГ</b> <tg-emoji emoji-id=\"5203934104143294160\">🔏</tg-emoji>",
    ),

    # ── Главное меню ──────────────────────────────────────────────────────────
    "choose_section": MessageConfig(
        key="choose_section",
                text=(
            "Можем переходить к анализу <tg-emoji emoji-id=\"5237948187838262194\">👁️</tg-emoji>\n\n"
            "Выбери, что хочешь посмотреть:"
        ),
        photo="menu.jpeg"
    ),
    "incomplete_profile": MessageConfig(
        key="incomplete_profile",
        text="Для анализа нужны <b>фото</b>, <b>имя</b> и <b>дата рождения</b>.\n\nПройди регистрацию: /start",
    ),

    # ── Self ──────────────────────────────────────────────────────────────────
    "self_intro": MessageConfig(
        key="self_intro",
        text=(
            "<tg-emoji emoji-id=\"5237948187838262194\">👁️</tg-emoji> <b>Анализ личности</b> - это глубокий анализ "
            "твоей внешности, психологических паттернов и скрытых особенностей, о которых ты даже не догадываешься\n\n"
            "Запустим тестовый анализ?"
        ),
        photo="self_main.jpeg"
    ),

    # ── Money ─────────────────────────────────────────────────────────────────
    "money_intro": MessageConfig(
        key="money_intro",
        text=(
            "<tg-emoji emoji-id=\"5366543795057881388\">🤑</tg-emoji> <b>Денежный потенциал</b> - разбор того, "
            "как ты привлекаешь деньги, где теряешь ресурсы и твои скрытые точки роста\n\n"
            "Запустим тестовый анализ?"
        ),
    ),

    # ── Couple ────────────────────────────────────────────────────────────────
    "couple_intro": MessageConfig(
        key="couple_intro",
        text=(
            "<tg-emoji emoji-id=\"5363887035662758185\">❤️</tg-emoji> <b>Совместимость пары</b> - разбор вашей "
            "динамики отношений, матриц, верности и кармы, а так же потенциал вашего союза и скрытых сторон "
            "партнера, о которых ты можешь не догадываться\n\n"
            "Запустим тестовый анализ?"
        ),
    ),

    # ── Пакеты ────────────────────────────────────────────────────────────────
    "choose_package": MessageConfig(
        key="choose_package",
        text="Выбери пакет:",
    ),
    "max_package": MessageConfig(
        key="max_package",
        text="У тебя уже <b>максимальный пакет</b> 🏆",
    ),

    # ── Пакеты: Self ──────────────────────────────────────────────────────────
    "pkg_self_base": MessageConfig(
        key="pkg_self_base",
        text=(
            "<b>Базовый пакет</b>\n\n"
            "Включает всё из демо, плюс два закрытых раздела:\n"
            "• <b>Ошибка, которая тормозит жизнь</b> — паттерн, который мешает двигаться вперёд\n"
            "• <b>Сценарий в отношениях</b> — как ты строишь близкие связи и где ломаешься"
        ),
    ),
    "pkg_self_extended": MessageConfig(
        key="pkg_self_extended",
        text=(
            "<b>Расширенный пакет</b>\n\n"
            "Всё из Базового, плюс:\n"
            "• <b>Жизненные сценарии</b> — глубокие программы, которые управляют твоими решениями\n"
            "• <b>Кармический урок</b> — то, что повторяется до тех пор, пока не осознано"
        ),
    ),
    "pkg_self_full": MessageConfig(
        key="pkg_self_full",
        text=(
            "<b>Премиум пакет</b>\n\n"
            "Полный отчёт — все блоки без ограничений:\n"
            "• <b>Скрытый талант</b> — ресурс, который ты скорее всего недооцениваешь\n"
            "• <b>Скрытая правда</b> — то, что проявляется, когда уходит контроль\n"
            "• <b>Сводный портрет</b> — итоговый психологический профиль"
        ),
    ),

    # ── Пакеты: Money ─────────────────────────────────────────────────────────
    "pkg_money_base": MessageConfig(
        key="pkg_money_base",
        text=(
            "<b>Базовый пакет</b> — Денежная карта\n\n"
            "Включает всё из демо, плюс:\n"
            "• <b>Главная причина финансовых проблем</b> — паттерн, который держит тебя в минусе\n"
            "• <b>Денежный код</b> — как именно деньги приходят к тебе по природе"
        ),
    ),
    "pkg_money_extended": MessageConfig(
        key="pkg_money_extended",
        text=(
            "<b>Расширенный пакет</b> — Денежная карта\n\n"
            "Всё из Базового, плюс:\n"
            "• <b>Денежный потолок</b> — твоя естественная зона и что её поднимает\n"
            "• <b>Стратегия заработка</b> — природный путь и лучшие сферы"
        ),
    ),
    "pkg_money_full": MessageConfig(
        key="pkg_money_full",
        text=(
            "<b>Премиум пакет</b> — Денежная карта\n\n"
            "Полный отчёт — все блоки:\n"
            "• <b>Финансовый прогноз на 5 лет</b> по личным годам\n"
            "• <b>Денежная сфера</b> — что притягивает и отталкивает деньги\n"
            "• <b>Финансовый якорь</b> — блокирующее убеждение и как его растворить\n"
            "• <b>Лучший момент для смены работы</b>"
        ),
    ),

    # ── Пакеты: Couple ────────────────────────────────────────────────────────
    "pkg_couple_base": MessageConfig(
        key="pkg_couple_base",
        text=(
            "<b>Базовый пакет</b> — Совместимость\n\n"
            "Включает всё из демо, плюс:\n"
            "• <b>Верность в паре</b> — риски и стабилизирующие факторы\n"
            "• <b>Карма в отношениях</b> — урок, который несёт пара вместе"
        ),
    ),
    "pkg_couple_extended": MessageConfig(
        key="pkg_couple_extended",
        text=(
            "<b>Расширенный пакет</b> — Совместимость\n\n"
            "Всё из Базового, плюс:\n"
            "• <b>Перспектива брака</b> по годам\n"
            "• <b>Уровень богатства в семье</b> — денежный паттерн пары\n"
            "• <b>Потенциал на детей</b> — оптимальное время"
        ),
    ),
    "pkg_couple_full": MessageConfig(
        key="pkg_couple_full",
        text=(
            "<b>Премиум пакет</b> — Совместимость\n\n"
            "Полный отчёт — все блоки:\n"
            "• <b>Длительность союза</b> — краткосрочная история или долгий путь\n"
            "• <b>Точка разрыва</b> — вероятность, триггер и что предотвратит"
        ),
    ),

    # ── Партнёр ───────────────────────────────────────────────────────────────
    "partner_name_empty": MessageConfig(
        key="partner_name_empty",
        text="Имя не может быть пустым <tg-emoji emoji-id=\"5348460861755262251\">✍️</tg-emoji>",
    ),
    "partner_name_saved": MessageConfig(
        key="partner_name_saved",
        text="Имя партнёра — <b>{name}</b>.\n\nТеперь напиши дату рождения партнёра в формате <b>ДД.ММ.ГГГГ</b> <tg-emoji emoji-id=\"5203934104143294160\">🔏</tg-emoji>",
    ),
    "partner_name_invalid": MessageConfig(
        key="partner_name_invalid",
        text="Пожалуйста, напиши имя текстом <tg-emoji emoji-id=\"5348460861755262251\">✍️</tg-emoji>",
    ),
    "partner_birthdate_invalid": MessageConfig(
        key="partner_birthdate_invalid",
        text="Неверный формат. Напиши дату в формате <b>ДД.ММ.ГГГГ</b>, например <code>14.06.1997</code> <tg-emoji emoji-id=\"5203934104143294160\">🔏</tg-emoji>",
    ),
    "partner_birthdate_invalid_type": MessageConfig(
        key="partner_birthdate_invalid_type",
        text="Пожалуйста, напиши дату текстом в формате <b>ДД.ММ.ГГГГ</b> <tg-emoji emoji-id=\"5203934104143294160\">🔏</tg-emoji>",
    ),
    "partner_photo_request": MessageConfig(
        key="partner_photo_request",
        text=(
            "Отлично! Теперь пришли фото партнёра <tg-emoji emoji-id=\"5395698544164233115\">🤩</tg-emoji>\n\n"
            "Это улучшит точность анализа. Если фото нет — нажми «Пропустить»."
        ),
    ),
    "partner_photo_invalid": MessageConfig(
        key="partner_photo_invalid",
        text="Пожалуйста, пришли именно <b>фото</b> <tg-emoji emoji-id=\"5395698544164233115\">🤩</tg-emoji> или нажми «Пропустить»",
    ),
    "partner_data_received": MessageConfig(
        key="partner_data_received",
        text="Данные партнёра получены <tg-emoji emoji-id=\"5395526217191416774\">🤩</tg-emoji>\n\nЗапускаю анализ совместимости <tg-emoji emoji-id=\"5256172434154866918\">🟠</tg-emoji>",
    ),

    # ── Анализ (статусы) ──────────────────────────────────────────────────────
    "analyzing": MessageConfig(
        key="analyzing",
        text="Запускаю анализ... Это займёт минуту <tg-emoji emoji-id=\"5256172434154866918\">🟠</tg-emoji>",
    ),
    "analyzing_couple": MessageConfig(
        key="analyzing_couple",
        text="Запускаю анализ совместимости... Это займёт минуту <tg-emoji emoji-id=\"5256172434154866918\">🟠</tg-emoji>",
    ),
    "analyzing_couple_short": MessageConfig(
        key="analyzing_couple_short",
        text="Запускаю анализ совместимости <tg-emoji emoji-id=\"5256172434154866918\">🟠</tg-emoji>",
    ),
    "analyzing_partner_photo": MessageConfig(
        key="analyzing_partner_photo",
        text="Анализирую фото партнёра <tg-emoji emoji-id=\"5256172434154866918\">🟠</tg-emoji>",
    ),

    # ── Ладони ────────────────────────────────────────────────────────────────
    "palm_needed_self": MessageConfig(
        key="palm_needed_self",
        text=(
            "<tg-emoji emoji-id=\"5262912590756982214\">👋</tg-emoji> <b>Ладони хранят больше информации, чем кажется</b>\n\n"
            "Для <b>премиум анализа</b> мне нужны фото обеих ладоней, это основа хиромантии.\n"
            "Начнём с <b>левой ладони</b> - пришли фото ладонью вверх (линии должны быть чётко видны)"
        ),
    ),
    "palm_needed_money": MessageConfig(
        key="palm_needed_money",
        text=(
            "<tg-emoji emoji-id=\"5262912590756982214\">👋</tg-emoji> <b>Линии ладоней могут показать, как ты взаимодействуешь с деньгами</b>\n\n"
            "Для <b>премиум анализа</b> пришли фото <b>левой ладони</b> - ладонью вверх (линии должны быть чётко видны)\n"
            "Нет фото? Нажми «Пропустить» — анализ ладоней будет пропущен."
        ),
    ),
    "palm_left_analyzing": MessageConfig(
        key="palm_left_analyzing",
        text="Анализирую левую ладонь <tg-emoji emoji-id=\"5256172434154866918\">🟠</tg-emoji>",
    ),
    "palm_right_analyzing": MessageConfig(
        key="palm_right_analyzing",
        text="Анализирую правую ладонь <tg-emoji emoji-id=\"5256172434154866918\">🟠</tg-emoji>",
    ),
    "palm_not_detected": MessageConfig(
        key="palm_not_detected",
        text=(
            "<tg-emoji emoji-id=\"5805364370376496031\">😎</tg-emoji>Не удалось распознать линии ладони\n\n"
            "Попробуй отправить другое фото - ладонь должна быть направлена вверх, хорошее освещение, "
            "линии должно быть чётко видны."
        ),
    ),
    "palm_left_accepted": MessageConfig(
        key="palm_left_accepted",
        text=(
            "<b>Получил!</b> <tg-emoji emoji-id=\"5395526217191416774\">🤩</tg-emoji>\n\n"
            "Теперь пришли фото <b>правой ладони</b> (ладонью вверх)\n"
            "Нет фото? Нажми «Пропустить»."
        ),
    ),
    "palm_both_accepted": MessageConfig(
        key="palm_both_accepted",
        text=(
            "<tg-emoji emoji-id=\"5222154218701352505\">✔️</tg-emoji>Линии ладоней успешно считаны\n\n"
            "Начинаю глубокий анализ <tg-emoji emoji-id=\"5256172434154866918\">🟠</tg-emoji>"
        ),
    ),
    "palm_photo_invalid": MessageConfig(
        key="palm_photo_invalid",
        text="Пожалуйста, пришли именно <b>фото ладони</b> <tg-emoji emoji-id=\"5395698544164233115\">🤩</tg-emoji>",
    ),

    # ── Ошибки ────────────────────────────────────────────────────────────────
    "partner_data_missing": MessageConfig(
        key="partner_data_missing",
        text="Данные партнёра не найдены <tg-emoji emoji-id=\"5805364370376496031\">😎</tg-emoji>\n\nНачни заново через меню.",
    ),
    "report_error": MessageConfig(
        key="report_error",
        text="<tg-emoji emoji-id=\"5805364370376496031\">😎</tg-emoji>Ошибка при генерации отчёта: <code>{error}</code>",
    ),
}


# ─── Хелперы отправки/редактирования ──────────────────────────────────────────

def _get_text(msg_key: str, **fmt) -> str:
    """Получить форматированный текст сообщения.

    Пользовательские значения автоматически экранируются для HTML.
    """
    config = MESSAGES[msg_key]
    if fmt:
        safe_fmt = {k: _html_escape(str(v)) for k, v in fmt.items()}
        return config.text.format(**safe_fmt)
    return config.text


async def send_msg(
    message: Message,
    msg_key: str,
    reply_markup=None,
    **fmt,
) -> Message:
    """Отправить сообщение с опциональной картинкой.

    Если в конфигурации сообщения указана картинка — отправляет как photo+caption.
    Иначе — как обычное текстовое сообщение.

    Returns:
        Отправленное сообщение.
    """
    text = _get_text(msg_key, **fmt)
    config = MESSAGES[msg_key]
    photo_path = config.photo_path

    if photo_path:
        photo = FSInputFile(str(photo_path))
        return await message.answer_photo(
            photo=photo,
            caption=text,
            reply_markup=reply_markup,
            parse_mode="HTML",
        )
    else:
        return await message.answer(
            text=text,
            reply_markup=reply_markup,
            parse_mode="HTML",
        )


async def edit_msg(
    message: Message,
    msg_key: str,
    reply_markup=None,
    **fmt,
) -> Message:
    """Редактировать сообщение с опциональной картинкой.

    Обрабатывает переходы между текстом и фото:
    - текст → текст: edit_text
    - фото → фото: edit_media (меняет и картинку, и подпись)
    - текст → фото: delete + send_photo
    - фото → текст: delete + send_message

    Returns:
        Актуальное сообщение (может отличаться от исходного при delete+resend).
    """
    text = _get_text(msg_key, **fmt)
    config = MESSAGES[msg_key]
    photo_path = config.photo_path
    has_photo_config = photo_path is not None
    message_has_photo = bool(message.photo)

    if has_photo_config and message_has_photo:
        # Оба с фото — обновляем медиа и подпись
        media = InputMediaPhoto(
            media=FSInputFile(str(photo_path)),
            caption=text,
            parse_mode="HTML",
        )
        try:
            return await message.edit_media(media=media, reply_markup=reply_markup)
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                return message
            raise

    elif not has_photo_config and not message_has_photo:
        # Оба без фото — edit_text
        try:
            return await message.edit_text(text=text, reply_markup=reply_markup, parse_mode="HTML")
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                return message
            raise

    else:
        # Структура изменилась (фото↔текст) — удаляем и отправляем заново
        chat_id = message.chat.id
        bot = message.bot
        try:
            await message.delete()
        except TelegramBadRequest:
            pass  # сообщение уже удалено

        if has_photo_config:
            photo = FSInputFile(str(photo_path))
            return await bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
        else:
            return await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )