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
│   └── templates/              ← HTML-шаблоны
│       ├── self_report.html.jinja
│       ├── couple_report.html.jinja
│       └── money_report.html.jinja
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
