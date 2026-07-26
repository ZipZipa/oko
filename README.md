# Reports Unified

Единый проект для генерации трёх типов персональных отчётов:
- **self** — персональный портрет одного человека (внешность, физиогномика, нумерология, матрица, глубинный анализ)
- **couple** — анализ совместимости пары (9 блоков от компатибилити до точки разрыва)
- **money** — денежный портрет одного человека (10 блоков от обзора до момента смены работы)

На вход — те же данные:
- DeepFace + MediaPipe JSON (для одного или двух человек)
- Имена и даты рождения

## Установка

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
```

## Использование

### Python API

```python
import json
from src.api import generate_report

with open("face.json") as f:
    face = json.load(f)

# Self
html = generate_report(
    report_type="self",
    face_data=face,
    name="Артём",
    birthdate="28.01.1995",
)

# Money
html = generate_report(
    report_type="money",
    face_data=face,
    name="Артём",
    birthdate="28.01.1995",
)

# Couple — нужны данные обоих
with open("face_b.json") as f:
    face_b = json.load(f)

html = generate_report(
    report_type="couple",
    face_data=face, name="Артём", birthdate="28.01.1995",
    face_data_b=face_b, name_b="Алина", birthdate_b="14.06.1997",
)

with open("report.html", "w", encoding="utf-8") as f:
    f.write(html)
```

### CLI

```bash
# Self
python -m src.cli self \
  --face examples/sample_face_artem.json \
  --name "Артём" --birthdate 28.01.1995 \
  --output output/self.html

# Money
python -m src.cli money \
  --face examples/sample_face_artem.json \
  --name "Артём" --birthdate 28.01.1995 \
  --output output/money.html

# Couple
python -m src.cli couple \
  --face examples/sample_face_artem.json --name "Артём" --birthdate 28.01.1995 \
  --face-b examples/sample_face_alina.json --name-b "Алина" --birthdate-b 14.06.1997 \
  --output output/couple.html
```

## Тестирование без API-ключа

```bash
python test_all.py
```

Этот скрипт проверит все валидаторы и отрендерит три отчёта на эталонных блоках — без вызова LLM.

## Архитектура

```
reports_unified/
├── src/
│   ├── api.py                  ← главный публичный API
│   ├── cli.py                  ← единый CLI
│   ├── core/                   ← общие модули
│   │   ├── numerology.py       ← числа жизненного пути, дня, пинаклы
│   │   ├── matrix.py           ← Матрица судьбы (6 позиций)
│   │   ├── archetypes.py       ← словари чисел и арканов
│   │   ├── features.py         ← черты лица из метрик
│   │   ├── scoring.py          ← скоры внешности 0-10
│   │   ├── money_dynamics.py   ← денежные архетипы, код, прогноз
│   │   ├── couple_dynamics.py  ← совместимость, число союза
│   │   ├── face_dynamics.py    ← контраст лиц, overlap матриц
│   │   ├── profile.py          ← общий построитель профиля человека
│   │   ├── llm_client.py       ← Claude API + retry
│   │   └── renderer.py         ← Jinja2 рендер
│   ├── reports/                ← по одному модулю на тип отчёта
│   │   ├── self_report.py      ← персональный
│   │   ├── couple_report.py    ← парный
│   │   └── money_report.py     ← денежный
│   ├── templates/              ← HTML-шаблоны
│   │   ├── self_report.html.jinja
│   │   ├── couple_report.html.jinja
│   │   └── money_report.html.jinja
│   └── web/                    ← мини-апп «Спросить ОКО» (aiohttp + WebApp)
├── examples/
│   ├── sample_face_artem.json
│   ├── sample_face_alina.json
│   ├── self/reference_blocks.json
│   ├── couple/reference_blocks.json
│   └── money/reference_blocks.json
├── output/                     ← готовые HTML
├── test_all.py                 ← тест без LLM
└── requirements.txt
```

## Что переиспользуется (core)

Все три типа отчётов используют:
- `numerology` — расчёт чисел из даты рождения
- `matrix` — расчёт матрицы судьбы
- `archetypes` — статические интерпретации чисел и арканов
- `features` — описания черт лица из метрик
- `profile.build_person_profile()` — единая сборка профиля
- `llm_client` — вызов Claude API с retry
- `renderer` — Jinja2

## Что у каждого отчёта своё (reports/)

Каждый модуль в `src/reports/` содержит:
- `SYSTEM_PROMPT` — специализированный для своего типа
- `build_user_prompt()` — сборка few-shot
- `REQUIRED_STRUCTURE` + `validate_blocks()` — схема выхода
- `build_target_input()` — что подавать в LLM
- `generate()` — главная функция отчёта

## Стоимость генерации (Sonnet 4.5)

- self: ~$0.10 за отчёт
- money: ~$0.13 за отчёт
- couple: ~$0.13 за отчёт

На Opus 4.7 — в ~5 раз дороже, тексты блоков «глубинный анализ» / «карма» / «якорь» лучше.

## Гарантии стабильности

- Все числа считаются Python — не LLM, всегда корректны
- LLM возвращает только JSON, не HTML — структура не ломается
- При битом JSON или нарушении схемы — retry с фидбеком (до 2 раз)
- Все эталоны проходят свои же валидаторы

## Расширение

### Добавить новый тип отчёта (например, "career")

1. Создать `src/reports/career_report.py` с тем же интерфейсом (SYSTEM_PROMPT, validate_blocks, build_target_input, generate)
2. Создать `src/templates/career_report.html.jinja`
3. Создать `examples/career/reference_blocks.json` с эталоном
4. Добавить в `src/api.py` ветку `if report_type == "career"`
5. Добавить в `src/cli.py` choices

### Расширить нумерологию

Все три отчёта подтянутся автоматически — нумерология общая.

### Подключить skin-модель

Заменить `score_skin_placeholder` в `src/core/scoring.py` на реальный анализ.
Затронет только self отчёт (couple и money не используют скоры внешности).

## Подводные камни

1. **Few-shot — главный рычаг качества.** Если хочешь улучшить какой-то тип отчёта — переписывай `examples/{type}/reference_blocks.json`. LLM копирует стиль эталона.

2. **Матрица упрощённая.** В `core/matrix.py` 6 базовых позиций. Полная матрица Ладини — 22 позиции. При желании расширяется (см. отдельную документацию).

3. **Хиромантия в couple и money — без фото ладоней.** Анализ идёт через черты лица. В системных промптах есть жёсткий запрет выдумывать линии.

4. **Скоры внешности нормированы эмпирически.** Для академической точности нужен референсный датасет (FFHQ) с расчётом перцентилей.

## Чат «Спросить ОКО» (Telegram WebApp)

Мини-апп, в котором пользователь обсуждает свой разбор и задаёт вопросы.
Открывается кнопкой в главном меню бота и кнопкой меню рядом с полем ввода.

```
src/web/
├── main.py       ← точка входа: python -m src.web.main
├── app.py        ← aiohttp: роуты, авторизация, SSE
├── auth.py       ← проверка подписи Telegram initData
├── chat.py       ← история, лимиты, системный промпт, стриминг
├── context.py    ← контекст для LLM: профиль + блоки отчётов
└── static/
    └── index.html ← мини-апп (вся вёрстка и скрипт в одном файле)
```

**Что чат видит.** Тот же материал, из которого собираются отчёты:
рассчитанный профиль (`build_person_profile` — нумерология, матрица, черты
лица, физиогномика, ладони) плюс тексты блоков всех сгенерированных отчётов
(self / money / couple). Контекст обрезается до `CHAT_CONTEXT_MAX_CHARS`
и кешируется по отпечатку данных пользователя.

**Лимит вопросов.** Доступ есть у всех, кто прошёл регистрацию. Количество
вопросов зависит от максимального купленного пакета среди всех отчётов:

| Пакет | Вопросов | Переменная |
|-------|----------|------------|
| ничего не куплено | 5 | `CHAT_LIMIT_DEMO` |
| Базовый | 30 | `CHAT_LIMIT_BASE` |
| Расширенный | 60 | `CHAT_LIMIT_EXTENDED` |
| Премиум | 200 | `CHAT_LIMIT_FULL` |

Счётчик живёт в `users.chat_questions_used` и не обнуляется при очистке
переписки. На исчерпании лимита мини-апп показывает экран с кнопкой, которая
присылает в бот сообщение с пакетами и закрывается.

**Авторизация.** Каждый запрос к `/api/*` несёт `initData` мини-аппа в заголовке
`X-Telegram-Init-Data`; подпись проверяется HMAC по `BOT_TOKEN`, initData
старше суток отклоняется.

**Данные.** Переписка — таблица `chat_messages`. События для аналитики:
`chat_opened`, `chat_message_sent`, `chat_limit_reached`.

**Локальный запуск** (без Telegram мини-апп не авторизует, но сервис поднимется):

```bash
python -m src.web.main       # 127.0.0.1:8080
curl -s localhost:8080/health
```

**Отладка в браузере.** Чтобы открыть мини-апп без Telegram, отключите проверку
подписи и укажите, чей профиль показывать:

```bash
# .env
WEBAPP_AUTH_DISABLED=1
WEBAPP_DEV_TELEGRAM_ID=123456789
```

```bash
python -m src.web.main
open http://localhost:8080                    # профиль из WEBAPP_DEV_TELEGRAM_ID
open http://localhost:8080/?tg_id=987654321   # любой другой пользователь
```

Пользователя можно переключать через `?tg_id=` или заголовок
`X-Debug-Telegram-Id` — это удобно, чтобы посмотреть чат глазами разных
пакетов. В этом режиме `BOT_TOKEN` не обязателен (не работает только кнопка
апселла). При старте сервис пишет в лог предупреждение, каждый запрос тоже
логируется как принятый без подписи.

> **Никогда не включайте `WEBAPP_AUTH_DISABLED` на сервере, доступном из
> интернета.** Флаг снимает авторизацию целиком: любой запрос с чужим
> `tg_id` откроет чужой разбор и потратит его лимит вопросов.

## Деплой

### Основной инстанс
```bash
sudo bash deploy/setup.sh
```

Скрипт клонирует репозиторий в `/opt/oko`, создаёт venv, устанавливает зависимости,
формирует `.env` и регистрирует systemd-сервис `oko-bot`.

### Мини-апп «Спросить ОКО»

Отдельный сервис `oko-web` на общей кодовой базе, venv и БД. Требует домена
с A-записью на этот сервер и открытых портов 80/443.

```bash
sudo bash deploy/setup-web.sh oko.example.com admin@example.com
```

Скрипт ставит nginx и certbot, прописывает `WEBAPP_URL` в `/opt/oko/.env`,
поднимает systemd-сервис `oko-web`, выпускает TLS-сертификат и перезапускает
`oko-bot` — иначе кнопка мини-аппа не появится (бот читает `WEBAPP_URL` при старте).

| Ресурс | Значение |
|--------|----------|
| systemd-сервис | `oko-web` |
| Порт (localhost) | `WEB_PORT`, по умолчанию 8080 |
| nginx-сайт | `/etc/nginx/sites-available/oko-web` |
| Логи | `journalctl -u oko-web -f` |

```bash
journalctl -u oko-web -f            # логи
systemctl restart oko-web           # рестарт
curl -s https://oko.example.com/health
```

**Важно про SQLite.** С мини-аппом в БД пишут два процесса. `init_db` включает
WAL и ставит запас по ожиданию блокировки, этого хватает для текущих нагрузок.
При заметном росте трафика переезжайте на PostgreSQL через `DATABASE_URL`.

**Отключить мини-апп:** уберите `WEBAPP_URL` из `.env` и перезапустите `oko-bot` —
кнопки пропадут, сервис можно остановить (`systemctl stop oko-web`).

### Дополнительный инстанс (test, staging и т.д.)

```bash
sudo bash deploy/deploy-instance.sh test
```

Скрипт создаёт **отдельный** инстанс бота с собственной конфигурацией и БД,
используя общую кодовую базу и venv. Что изолируется:

| Ресурс | Основной | Дополнительный |
|--------|----------|----------------|
| `.env` | `/opt/oko/.env` | `/opt/oko/.env-test` |
| БД (SQLite) | `oko_bot.db` | `oko_bot_test.db` |
| systemd-сервис | `oko-bot` | `oko-bot-test` |
| Логи | `journalctl -u oko-bot` | `journalctl -u oko-bot-test` |

**Важно:** каждый инстанс должен использовать **токен другого бота** от @BotFather
(Telegram не позволяет двум процессам работать с одним токеном одновременно).

При использовании PostgreSQL укажите отдельную базу в `DATABASE_URL`:

```
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/oko_test
```

Управление инстансом:

```bash
journalctl -u oko-bot-test -f      # логи
systemctl status oko-bot-test       # статус
systemctl restart oko-bot-test      # рестарт
systemctl stop oko-bot-test         # стоп
```

Удаление инстанса:

```bash
systemctl stop oko-bot-test
systemctl disable oko-bot-test
rm /etc/systemd/system/oko-bot-test.service
rm /opt/oko/.env-test
rm /opt/oko/oko_bot_test.db   # если используется SQLite
systemctl daemon-reload
```
