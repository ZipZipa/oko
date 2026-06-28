"""Централизованная конфигурация сообщений бота.

Каждое сообщение описано в одном месте — текст и опциональные картинки.
Для изменения текста или добавления/удаления картинок достаточно изменить MESSAGES.

Структура:
- MessageConfig — конфигурация одного сообщения (текст + опциональные картинки)
- MESSAGES — словарь всех сообщений бота
- send_msg() — отправка сообщения с учётом конфигурации
- edit_msg() — редактирование сообщения с учётом конфигурации
"""
from dataclasses import dataclass, field
from pathlib import Path

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
        photos: Список имён файлов картинок из директории media/ (может быть пустым)
        sale: Если True — к пушу добавляется кнопка «Получить скидку»
        delay_minutes: Через сколько минут после события отправить пуш (только для пушей)
    """
    key: str
    text: str
    photos: list[str] = field(default_factory=list)  # имена файлов из MEDIA_DIR
    sale: bool = False
    delay_minutes: int | None = None

    @property
    def photo_paths(self) -> list[Path]:
        """Список полных путей к существующим файлам картинок."""
        result: list[Path] = []
        for name in self.photos:
            path = MEDIA_DIR / name
            if path.exists():
                result.append(path)
        return result


# ─── Все сообщения бота ────────────────────────────────────────────────────────
# Чтобы добавить картинки к сообщению, укажи имена файлов в поле photos.
# Файлы должны лежать в директории src/bot/media/.
# Пример: photos=["img1.jpeg", "img2.jpeg"]

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
        photos=["intro.jpeg"]
    ),
    "start_returning_no_name": MessageConfig(
        key="start_returning_no_name",
        text=(
            "С возвращением! <tg-emoji emoji-id=\"5237948187838262194\">👁️</tg-emoji>\n\n"
            "Для начала, напиши свое имя <tg-emoji emoji-id=\"5348460861755262251\">✍️</tg-emoji>"
        ),
    ),
    "start_returning_no_photo": MessageConfig(
        key="start_returning_no_photo",
        text=(
            "С возвращением, <b>{name}</b>! <tg-emoji emoji-id=\"5237948187838262194\">👁️</tg-emoji>\n\n"
            "Для анализа нужно твоё фото — пришли селфи <tg-emoji emoji-id=\"5395698544164233115\">🤩</tg-emoji>"
        ),
        photos=["man.jpg","woman.jpg"]
    ),
    "start_returning_no_birthdate": MessageConfig(
        key="start_returning_no_birthdate",
        text=(
            "С возвращением, <b>{name}</b>! <tg-emoji emoji-id=\"5237948187838262194\">👁️</tg-emoji>\n\n"
            "Отправь дату рождения в формате <b>ДД.ММ.ГГГГ</b> <tg-emoji emoji-id=\"5203934104143294160\">🔏</tg-emoji>"
        ),
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
        photos=["man.jpg","woman.jpg"]
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
        photos=["menu.jpeg"]
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
        photos=["self/demo.jpeg"]
    ),

    # ── Money ─────────────────────────────────────────────────────────────────
    "money_intro": MessageConfig(
        key="money_intro",
        text=(
            "<tg-emoji emoji-id=\"5366543795057881388\">🤑</tg-emoji> <b>Денежный потенциал</b> - разбор того, "
            "как ты привлекаешь деньги, где теряешь ресурсы и твои скрытые точки роста\n\n"
            "Запустим тестовый анализ?"
        ),
        photos=["money/demo.jpeg"]
    ),

    # ── Couple ────────────────────────────────────────────────────────────────
    "couple_intro": MessageConfig(
        key="couple_intro",
        text=(
            "<tg-emoji emoji-id=\"5363887035662758185\">❤️</tg-emoji> <b>Совместимость пары</b> - разбор вашей "
            "динамики отношений, динамики отношений, верности и кармы, а так же потенциал вашего союза и скрытых сторон "
            "партнера, о которых ты можешь не догадываться\n\n"
            "Запустим тестовый анализ?"
        ),
        photos=["couple/demo.jpeg"]
    ),

    # ── Пакеты ────────────────────────────────────────────────────────────────
    "choose_package_self": MessageConfig(
        key="choose_package_self",
        text="Выбери пакет для <b>Портрета личности</b>:",
        photos=["self/all.jpeg"]
    ),
    "choose_package_money": MessageConfig(
        key="choose_package_money",
        text="Выбери пакет для <b>Денежной карты</b>:",
        photos=["money/all.jpeg"]
    ),
    "choose_package_couple": MessageConfig(
        key="choose_package_couple",
        text="Выбери пакет для <b>Совместимости пары</b>:",
        photos=["couple/all.jpeg"]
    ),
    "max_package": MessageConfig(
        key="max_package",
        text="У тебя уже <b>максимальный пакет</b> 🏆",
    ),

    # ── Пакеты: Self ──────────────────────────────────────────────────────────
    "pkg_self_base": MessageConfig(
        key="pkg_self_base",
        text=(
            "<b>Базовый · Портрет личности</b>\n\n"
            "Большинство людей не знают, кем они являются на самом деле.\n\n"
            "Этот отчёт — первый честный взгляд на себя.\n\n"
        ),
        photos=["self/base.jpeg"]
    ),
    "pkg_self_extended": MessageConfig(
        key="pkg_self_extended",
        text=(
            "<b>Расширенный · Портрет личности</b>\n\n"
            "Почему одни и те же ситуации повторяются снова и снова?\n\n"
            "Здесь — ответ и выход.\n\n"
        ),
        photos=["self/extra.jpeg"]
    ),
    "pkg_self_full": MessageConfig(
        key="pkg_self_full",
        text=(
            "<b>Премиум · Портрет личности</b>\n\n"
            "То, что ты чувствуешь, но не можешь объяснить — здесь это получит имя и объяснение."
        ),
        photos=["self/full.jpeg"]
    ),

    # ── Пакеты: Money ─────────────────────────────────────────────────────────
    "pkg_money_base": MessageConfig(
        key="pkg_money_base",
        text=(
            "<b>Базовый · Денежная карта</b>\n"
            "Деньги не приходят случайно — и не уходят тоже."
            "Узнай, что стоит между тобой и другим уровнем."
        ),
        photos=["money/base.jpeg"]
    ),
    "pkg_money_extended": MessageConfig(
        key="pkg_money_extended",
        text=(
            "<b>Расширенный · Денежная карта</b>\n\n"
            "Ты работаешь — а результат не тот."
            "Здесь видно где утечка и как это исправить."
        ),
        photos=["money/extra.jpeg"]
    ),
    "pkg_money_full": MessageConfig(
        key="pkg_money_full",
        text=(
            "<b>Премиум · Денежная карта</b>\n\n"
            "Полная карта твоих денег: блоки, потенциал, лучшие годы для роста. Ничего не скрыто."
        ),
        photos=["money/full.jpeg"]
    ),

    # ── Пакеты: Couple ────────────────────────────────────────────────────────
    "pkg_couple_base": MessageConfig(
        key="pkg_couple_base",
        text=(
            "<b>Базовый · Совместимость</b>\n\n"
            "Что он/она на самом деле чувствует к тебе — и есть ли у этого будущее."
        ),
        photos=["couple/base.jpeg"]
    ),
    "pkg_couple_extended": MessageConfig(
        key="pkg_couple_extended",
        text=(
            "<b>Расширенный · Совместимость</b>\n\n"
            "Притяжение — это одно."
            "Совместимость — совсем другое. Разберём вашу пару глубже."
        ),
        photos=["couple/extra.jpeg"]
    ),
    "pkg_couple_full": MessageConfig(
        key="pkg_couple_full",
        text=(
            "<b>Премиум · Совместимость</b>\n\n"
            "Любовь, деньги, дети, верность — всё про вашу пару."
            "Полная правда без иллюзий."
        ),
        photos=["couple/full.jpeg"]
    ),

    # ── Партнёр ───────────────────────────────────────────────────────────────
    "partner_name_prompt": MessageConfig(
        key="partner_name_prompt",
        text="Напиши <b>имя партнёра</b> <tg-emoji emoji-id=\"5348460861755262251\">✍️</tg-emoji>",
    ),
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
        text="Пришли <b>фото партнёра</b> <tg-emoji emoji-id=\"5395698544164233115\">🤩</tg-emoji>",
    ),
    "partner_photo_invalid": MessageConfig(
        key="partner_photo_invalid",
        text="Пожалуйста, пришли именно <b>фото</b> <tg-emoji emoji-id=\"5395698544164233115\">🤩</tg-emoji>",
    ),
    "partner_palm_request": MessageConfig(
        key="partner_palm_request",
        text=(
            "<tg-emoji emoji-id=\"5262912590756982214\">👋</tg-emoji> <b>Ладони партнёра усилят анализ совместимости</b>\n\n"
            "Анализ линий ладони раскроет скрытые паттерны в отношениях и кармические связи.\n\n"
            "Пришли фото <b>левой ладони партнёра</b> (ладонью вверх, линии должны быть чётко видны)\n"
            "Или нажми «Пропустить»."
        ),
    ),
    "partner_palm_left_done": MessageConfig(
        key="partner_palm_left_done",
        text=(
            "<b>Левая ладонь партнёра считана!</b> <tg-emoji emoji-id=\"5395526217191416774\">🤩</tg-emoji>\n\n"
            "Теперь пришли <b>правую ладонь партнёра</b> (ладонью вверх)\n"
            "Или нажми «Пропустить»."
        ),
    ),
    "partner_palm_skipped": MessageConfig(
        key="partner_palm_skipped",
        text="Хорошо, ладони партнёра можно добавить позже <tg-emoji emoji-id=\"5222154218701352505\">✔️</tg-emoji>\n\n",
    ),
    "partner_data_received": MessageConfig(
        key="partner_data_received",
        text="Данные партнёра получены <tg-emoji emoji-id=\"5395526217191416774\">🤩</tg-emoji>\n\nЗапускаю анализ совместимости <tg-emoji emoji-id=\"5256172434154866918\">🟠</tg-emoji>",
    ),

    # ── Анализ (статусы) ──────────────────────────────────────────────────────
    "analyzing": MessageConfig(
        key="analyzing",
        text="Запускаю анализ. Это займет некоторое время <tg-emoji emoji-id=\"5256172434154866918\">🟠</tg-emoji>",
    ),

    # ── Ладони при регистрации ────────────────────────────────────────────────
    "registration_palm_request": MessageConfig(
        key="registration_palm_request",
        text=(
            "<tg-emoji emoji-id=\"5262912590756982214\">👋</tg-emoji> <b>Ладони хранят больше информации, чем кажется</b>\n\n"
            "Фото ладоней усилят анализ — анализ линий ладони раскроет скрытые таланты, денежные линии и кармические уроки.\n\n"
            "Пришли фото <b>левой ладони</b> (ладонью вверх, линии должны быть чётко видны)\n"
            "Или нажми «Пропустить» — можно добавить ладони позже."
        ),
    ),
    "registration_palm_left_done": MessageConfig(
        key="registration_palm_left_done",
        text=(
            "<b>Левая ладонь считана!</b> <tg-emoji emoji-id=\"5395526217191416774\">🤩</tg-emoji>\n\n"
            "Теперь пришли <b>правую ладонь</b> (ладонью вверх)\n"
            "Или нажми «Пропустить»."
        ),
    ),
    "registration_palm_skipped": MessageConfig(
        key="registration_palm_skipped",
        text=(
            "Хорошо, ладони можно добавить позже <tg-emoji emoji-id=\"5222154218701352505\">✔️</tg-emoji>\n\n"
        ),
    ),
    "registration_palm_done": MessageConfig(
        key="registration_palm_done",
        text=(
            "<tg-emoji emoji-id=\"5222154218701352505\">✔️</tg-emoji> <b>Ладонии успешно считаны!</b>\n\n"
            "Анализ ладоней добавлен в твой профиль — это усилит будущие анализы.\n"
        ),
    ),

    # ── Ладони для couple full ───────────────────────────────────────────────
    "palm_needed_couple": MessageConfig(
        key="palm_needed_couple",
        text=(
            "<tg-emoji emoji-id=\"5262912590756982214\">👋</tg-emoji> <b>Ладоны усилят анализ совместимости</b>\n\n"
            "Хиромантия раскроет скрытые паттерны в отношениях и кармические связи.\n\n"
            "Для премиум-анализа нужны твои ладони. Пришли фото <b>левой ладони</b> (ладонью вверх, линии должны быть чётко видны)\n"
            "Или нажми «Пропустить»."
        ),
    ),
    "partner_palm_needed_premium": MessageConfig(
        key="partner_palm_needed_premium",
        text=(
            "<tg-emoji emoji-id=\"5262912590756982214\">👋</tg-emoji> <b>Ладони партнёра усилят анализ совместимости</b>\n\n"
            "Анализ линий ладони раскроет скрытые паттерны в отношениях и кармические связи.\n\n"
            "Пришли фото <b>левой ладони партнёра</b> (ладонью вверх, линии должны быть чётко видны)\n"
            "Или нажми «Пропустить»."
        ),
    ),

    # ── Ладони ────────────────────────────────────────────────────────────────
    "palm_needed_self": MessageConfig(
        key="palm_needed_self",
        text=(
            "<tg-emoji emoji-id=\"5262912590756982214\">👋</tg-emoji> <b>Ладони хранят больше информации, чем кажется</b>\n\n"
            "Для <b>премиум анализа</b> мне нужны фото обеих ладоней, это основа глубокого анализа.\n"
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

    # ── Оплата ────────────────────────────────────────────────────────────────
    "payment_created": MessageConfig(
        key="payment_created",
        text=(
            "💳 <b>Оплата</b>\n\n"
            "{report} · {plan}\n\n"
            "Сумма: <b>{price} ₽</b>\n\n"
            "Нажми кнопку ниже, чтобы перейти к оплате.\n"
            "После оплаты нажми «<tg-emoji emoji-id=\"5206607081334906820\">✅</tg-emoji> Я оплатил».\n\n"
            "<blockquote expandable>"
            "Данная ссылка действительна в течение 10 минут.\n"
            "После оплаты вам будет предоставлен персонализированный доступ к услугам и материалам внутри бота согласно выбранному тарифу.\n"
            "Оплата является разовой и производится единым платежом. Автоматических продлений, подписок и повторных списаний не предусмотрено.\n"
            "Нажимая кнопку оплаты и переходя по ссылке, вы подтверждаете своё согласие с условиями "
            "<a href=\"https://telegra.ph/PUBLICHNAYA-OFERTA-06-23-11\">Публичной оферты</a>, "
            "<a href=\"https://telegra.ph/POLZOVATELSKOE-SOGLASHENIE-06-23-26\">Пользовательского соглашения</a>, "
            "<a href=\"https://telegra.ph/POLITIKA-KONFIDENCIALNOSTI-I-OBRABOTKI-PERSONALNYH-DANNYH-06-23\">Политики конфиденциальности и Политики обработки персональных данных (ОПД)</a>.\n"
            "После успешной оплаты доступ к приобретённой услуге будет предоставлен автоматически в соответствии с условиями, указанными в боте."
            "</blockquote>"
        ),
    ),
    "payment_success": MessageConfig(
        key="payment_success",
        text="<tg-emoji emoji-id=\"5222154218701352505\">✔️</tg-emoji> Оплата прошла успешно! Запускаю генерацию отчёта <tg-emoji emoji-id=\"5256172434154866918\">🟠</tg-emoji>",
    ),
    "payment_pending": MessageConfig(
        key="payment_pending",
        text="⏳ Платёж ещё не подтверждён. Попробуй проверить через несколько секунд.",
    ),
    "payment_cancelled": MessageConfig(
        key="payment_cancelled",
        text="❌ Платёж отменён. Попробуй оплатить заново.",
    ),
    "payment_error": MessageConfig(
        key="payment_error",
        text="<tg-emoji emoji-id=\"5447644880824181073\">⚠️</tg-emoji> Ошибка оплаты: {error}",
    ),
    "payment_create_error": MessageConfig(
        key="payment_create_error",
        text="<tg-emoji emoji-id=\"5447644880824181073\">⚠️</tg-emoji> Не удалось создать платёж: {error}",
    ),

    # ── Сброс данных ──────────────────────────────────────────────────────────
    "reset_confirm": MessageConfig(
        key="reset_confirm",
        text=(
            "<tg-emoji emoji-id=\"5447644880824181073\"><tg-emoji emoji-id=\"5447644880824181073\">⚠️</tg-emoji></tg-emoji> <b>Сброс данных</b>\n\n"
            "Будут удалены все результаты отчётов (Портрет личности, Денежная карта, Совместимость пары), "
            "а также данные партнёра и ладоней.\n\n"
            "Ранее полученные отчеты сохранятся в вашем чате.\n\n"
            "После сброса тебе нужно будет пройти регистрацию заново.\n\n"
            "Продолжить?"
        ),
    ),
    "reset_done": MessageConfig(
        key="reset_done",
        text=(
            "<tg-emoji emoji-id=\"5206607081334906820\">✅</tg-emoji> <b>Данные сброшены</b>\n\n"
            "Все результаты отчётов удалены. Начнём заново!"
        ),
    ),

    # ── Ошибки ────────────────────────────────────────────────────────────────
    "partner_face_missing": MessageConfig(
        key="partner_face_missing",
        text="Не удалось распознать лицо на фото партнёра <tg-emoji emoji-id=\"5805364370376496031\">😎</tg-emoji>\n\nЗагрузи другое фото — хорошо освещённое, анфас, с чётко видимым лицом.",
    ),
    "partner_data_missing": MessageConfig(
        key="partner_data_missing",
        text="Данные партнёра не найдены <tg-emoji emoji-id=\"5805364370376496031\">😎</tg-emoji>\n\nНачни заново через меню.",
    ),
    "report_error": MessageConfig(
        key="report_error",
        text="<tg-emoji emoji-id=\"5805364370376496031\">😎</tg-emoji>Ошибка при генерации отчёта: <code>{error}</code>",
    ),

    # ── Пуши (воронка) ────────────────────────────────────────────────────────
    # E1: Зашёл → ничего не начал
    "push_e1_1": MessageConfig(
        key="push_e1_1",
        text="👁️ Твой персональный анализ ещё не начат.",
        delay_minutes=15,
    ),
    "push_e1_2": MessageConfig(
        key="push_e1_2",
        text="Ответы о тебе всё ещё ждут тебя в ОКО.",
        delay_minutes=1440,
    ),
    # E2: Начал анализ → бросил на заполнении данных
    "push_e2_1": MessageConfig(
        key="push_e2_1",
        text="Ты почти начал анализ. Остался последний шаг.",
        delay_minutes=30,
    ),
    "push_e2_2": MessageConfig(
        key="push_e2_2",
        text="Дополни данные и получи свой персональный разбор.",
        delay_minutes=720,
    ),
    # E3: Начал совместимость → не ввёл партнёра
    "push_e3_1": MessageConfig(
        key="push_e3_1",
        text="Для анализа пары не хватает данных второго человека.",
        delay_minutes=30,
    ),
    "push_e3_2": MessageConfig(
        key="push_e3_2",
        text="Добавь данные партнёра и узнай, что происходит между вами на самом деле.",
        delay_minutes=1440,
    ),
    # E4: Получил демо → не купил
    # self
    "push_e4_1_self": MessageConfig(
        key="push_e4_1_self",
        text="Ты увидел только часть анализа личности.",
        delay_minutes=20,
    ),
    "push_e4_2_self": MessageConfig(
        key="push_e4_2_self",
        text="Самые важные выводы о тебе остались закрыты.",
        sale=True,
        delay_minutes=720,
    ),
    "push_e4_3_self": MessageConfig(
        key="push_e4_3_self",
        text="Полный разбор личности всё ещё доступен.",
        sale=True,
        delay_minutes=2880,
    ),
    # money
    "push_e4_1_money": MessageConfig(
        key="push_e4_1_money",
        text="Ты увидел только часть денежного анализа.",
        delay_minutes=20,
    ),
    "push_e4_2_money": MessageConfig(
        key="push_e4_2_money",
        text="Самые важные выводы о твоих деньгах остались закрыты.",
        sale=True,
        delay_minutes=720,
    ),
    "push_e4_3_money": MessageConfig(
        key="push_e4_3_money",
        text="Полный денежный разбор всё ещё доступен.",
        sale=True,
        delay_minutes=2880,
    ),
    # couple
    "push_e4_1_couple": MessageConfig(
        key="push_e4_1_couple",
        text="Ты увидел только часть анализа совместимости.",
        delay_minutes=20,
    ),
    "push_e4_2_couple": MessageConfig(
        key="push_e4_2_couple",
        text="Самые важные выводы о вашей паре остались закрыты.",
        sale=True,
        delay_minutes=720,
    ),
    "push_e4_3_couple": MessageConfig(
        key="push_e4_3_couple",
        text="Полный разбор совместимости всё ещё доступен.",
        sale=True,
        delay_minutes=2880,
    ),
    # E5: Нажал оплатить → не оплатил
    "push_e5_1": MessageConfig(
        key="push_e5_1",
        text="Оплата не завершена. Твой анализ уже готов.",
        delay_minutes=15,
    ),
    "push_e5_2": MessageConfig(
        key="push_e5_2",
        text="Остался один шаг до полного доступа.",
        sale=True,
        delay_minutes=180,
    ),
    "push_e5_3": MessageConfig(
        key="push_e5_3",
        text="Заверши оплату и открой свой разбор.",
        sale=True,
        delay_minutes=1440,
    ),
    # E6: Купил один продукт → не купил остальные
    "push_e6_self": MessageConfig(
        key="push_e6_self",
        text="Теперь узнай, как твои особенности влияют на деньги и отношения.",
        delay_minutes=1440,
    ),
    "push_e6_money": MessageConfig(
        key="push_e6_money",
        text="Теперь узнай, какие отношения усиливают или ослабляют твой путь.",
        delay_minutes=1440,
    ),
    "push_e6_couple": MessageConfig(
        key="push_e6_couple",
        text="Теперь узнай, почему именно такие люди появляются в твоей жизни.",
        delay_minutes=1440,
    ),
    # E7: Купил базовый/расширенный → не купил премиум
    # self
    "push_e7_1_self": MessageConfig(
        key="push_e7_1_self",
        text="Ты открыл только часть анализа личности.",
        delay_minutes=120,
    ),
    "push_e7_2_self": MessageConfig(
        key="push_e7_2_self",
        text="Самые глубокие выводы о тебе доступны в Премиум.",
        sale=True,
        delay_minutes=1440,
    ),
    # money
    "push_e7_1_money": MessageConfig(
        key="push_e7_1_money",
        text="Ты открыл только часть денежного анализа.",
        delay_minutes=120,
    ),
    "push_e7_2_money": MessageConfig(
        key="push_e7_2_money",
        text="Самые глубокие выводы о твоих деньгах доступны в Премиум.",
        sale=True,
        delay_minutes=1440,
    ),
    # couple
    "push_e7_1_couple": MessageConfig(
        key="push_e7_1_couple",
        text="Ты открыл только часть анализа совместимости.",
        delay_minutes=120,
    ),
    "push_e7_2_couple": MessageConfig(
        key="push_e7_2_couple",
        text="Самые глубокие выводы о вашей паре доступны в Премиум.",
        sale=True,
        delay_minutes=1440,
    ),
    # E8: Давно не заходил
    "push_e8_1": MessageConfig(
        key="push_e8_1",
        text="Твои разборы всё ещё ждут тебя.",
        delay_minutes=10080,
    ),
    "push_e8_2": MessageConfig(
        key="push_e8_2",
        text="Возможно, сейчас именно то время, чтобы посмотреть на свою жизнь иначе.",
        delay_minutes=43200,
    ),

    # ── Скидка ────────────────────────────────────────────────────────────────
    "sale_applied": MessageConfig(
        key="sale_applied",
        text="🎁 <b>Скидка 20% применена!</b>\n\nТеперь все пакеты доступны дешевле. Выбери свой разбор:",
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


def _resolve_photo_paths(msg_key: str, photos: list[str] | None = None) -> list[Path]:
    """Resolve photo paths: explicit override → config photos → empty."""
    if photos is not None:
        result: list[Path] = []
        for name in photos:
            path = MEDIA_DIR / name
            if path.exists():
                result.append(path)
        return result
    return MESSAGES[msg_key].photo_paths


async def send_msg(
    message: Message,
    msg_key: str,
    reply_markup=None,
    photos: list[str] | None = None,
    **fmt,
) -> Message:
    """Отправить сообщение с опциональными картинками.

    - 0 фото: обычное текстовое сообщение
    - 1 фото:  photo + caption (поддерживает reply_markup)
    - 2+ фото: медиагруппа; reply_markup отправляется отдельным сообщением
               (Telegram API не поддерживает reply_markup для медиагрупп)

    Args:
        photos: Override-список имён файлов из media/ (вместо конфига сообщения).

    Returns:
        Последнее отправленное сообщение.
    """
    text = _get_text(msg_key, **fmt)
    paths = _resolve_photo_paths(msg_key, photos)

    if not paths:
        return await message.answer(
            text=text,
            reply_markup=reply_markup,
            parse_mode="HTML",
        )

    if len(paths) == 1:
        photo = FSInputFile(str(paths[0]))
        return await message.answer_photo(
            photo=photo,
            caption=text,
            reply_markup=reply_markup,
            parse_mode="HTML",
        )

    # 2+ фото — медиагруппа
    media_list: list[InputMediaPhoto] = []
    for i, p in enumerate(paths):
        media_list.append(InputMediaPhoto(
            media=FSInputFile(str(p)),
            caption=text if i == 0 else None,
            parse_mode="HTML" if i == 0 else None,
        ))

    await message.answer_media_group(media=media_list)

    # reply_markup не поддерживается для медиагрупп —
    # отправляем отдельное сообщение с клавиатурой
    if reply_markup:
        return await message.answer(
            text="↑",
            reply_markup=reply_markup,
        )

    # Возвращаем последнее сообщение из медиагруппы (хотя достать его сложно,
    # answer_media_group возвращает список). Возвращаем заглушку.
    return message


async def edit_msg(
    message: Message,
    msg_key: str,
    reply_markup=None,
    photos: list[str] | None = None,
    **fmt,
) -> Message:
    """Редактировать сообщение с опциональными картинками.

    Обрабатывает переходы между текстом и фото:
    - текст → текст: edit_text
    - 1 фото → 1 фото: edit_media (меняет и картинку, и подпись)
    - в остальных случаях: delete + resend

    Args:
        photos: Override-список имён файлов из media/ (вместо конфига сообщения).

    Returns:
        Актуальное сообщение (может отличаться от исходного при delete+resend).
    """
    text = _get_text(msg_key, **fmt)
    paths = _resolve_photo_paths(msg_key, photos)
    has_photos = len(paths) > 0
    message_has_photo = bool(message.photo)

    # Простой случай: 1 фото → 1 фото — обновляем медиа и подпись
    if has_photos and len(paths) == 1 and message_has_photo:
        media = InputMediaPhoto(
            media=FSInputFile(str(paths[0])),
            caption=text,
            parse_mode="HTML",
        )
        try:
            return await message.edit_media(media=media, reply_markup=reply_markup)
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                return message
            raise

    # Простой случай: текст → текст
    if not has_photos and not message_has_photo:
        try:
            return await message.edit_text(text=text, reply_markup=reply_markup, parse_mode="HTML")
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                return message
            raise

    # Во всех остальных случаях — удаляем и отправляем заново
    chat_id = message.chat.id
    bot = message.bot
    try:
        await message.delete()
    except TelegramBadRequest:
        pass  # сообщение уже удалено

    try:
        if not has_photos:
            return await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )

        if len(paths) == 1:
            photo = FSInputFile(str(paths[0]))
            return await bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )

        # 2+ фото — медиагруппа
        media_list: list[InputMediaPhoto] = []
        for i, p in enumerate(paths):
            media_list.append(InputMediaPhoto(
                media=FSInputFile(str(p)),
                caption=text if i == 0 else None,
                parse_mode="HTML" if i == 0 else None,
            ))

        await bot.send_media_group(chat_id=chat_id, media=media_list)

        # reply_markup не поддерживается для медиагрупп
        if reply_markup:
            return await bot.send_message(
                chat_id=chat_id,
                text="↑",
                reply_markup=reply_markup,
            )

        return message
    except Exception:
        # Если отправка с фото не удалась — отправляем хотя бы текстовое сообщение
        try:
            return await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
        except Exception:
            return message
