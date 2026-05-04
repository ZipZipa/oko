Принцип изменения отчетов на трёх уровнях — от самого простого до сложного.
Уровень 1: Поправить тексты в существующих отчётах
Самое частое и простое. Меняешь только эталонные блоки — структура, числа, шаблон не трогаются.
Файл: examples/{self|couple|money}/reference_blocks.json
Когда нужно:

Не нравится тон отчётов в каком-то блоке
Хочешь добавить/убрать пункт в strengths/weaknesses
Хочешь поменять цитаты, финальные строки

Что делать:

Открываешь нужный JSON
Правишь текст
Запускаешь python test_all.py — проверяешь что валидатор не ругается

Всё. На следующем вызове LLM подхватит новый стиль. Кода менять не нужно.

Уровень 2: Добавить новый блок в существующий отчёт
Допустим, в money хочешь добавить блок «Долговой паттерн».
Шаги:
Шаг 1. Эталон блока
В examples/money/reference_blocks.json добавляешь новый ключ:
json"debt_pattern": {
  "intro_quote": "Долги — не зло сами по себе, вопрос — кто кем владеет",
  "type": "пользователь долга",
  "behavior": "берёшь долги под конкретные активы, не на потребление",
  "warning_signs": [
    "...",
    "..."
  ],
  "final_line": "Деньги в долг — это твой инструмент, а не клетка."
}
Шаг 2. Валидатор
В src/reports/money_report.py находишь REQUIRED_STRUCTURE и добавляешь:
pythonREQUIRED_STRUCTURE = {
    ...
    "debt_pattern": ["intro_quote", "type", "behavior", "warning_signs", "final_line"],
}
Шаг 3. Шаблон
В src/templates/money_report.html.jinja добавляешь новую секцию (где-нибудь между блоками VIII и IX):
html<div class="chapter-divider">
  <div class="chap-eyebrow">Часть восьмая+</div>
  <div class="chap-title-big">Долговой паттерн</div>
  <div class="chap-num">VIII+</div>
</div>
<div class="page">
  <div class="card">
    <p class="q">{{ blocks.debt_pattern.intro_quote }}</p>
    <div class="card-lbl">Тип</div>
    <div class="bt">{{ blocks.debt_pattern.type }}</div>
    <div class="card-lbl">Поведение</div>
    <div class="bt">{{ blocks.debt_pattern.behavior }}</div>
    <div class="card-lbl">Сигналы тревоги</div>
    <div class="bt">
      {% for sign in blocks.debt_pattern.warning_signs %}
      <div class="ri"><div class="dh"></div><span>{{ sign }}</span></div>
      {% endfor %}
    </div>
    <div class="final-line">{{ blocks.debt_pattern.final_line }}</div>
  </div>
</div>
Шаг 4. Перенумеруй части в TOC и заголовках (опционально, для аккуратности).
Шаг 5. Тест
bashpython test_all.py
Если эталон валиден — всё. На следующем реальном вызове Claude увидит в эталоне новый блок и сгенерит такой же для нового пользователя.
Важно: ничего не нужно делать с prompt_builder или core модулями. Промпт и так передаёт весь эталон LLM, включая новый блок.

Уровень 3: Добавить новый расчёт в core
Допустим, хочешь, чтобы во всех отчётах считался «вибрационный код имени» (числовое значение имени по нумерологии).
Шаги:
Шаг 1. Расчёт в core
Создаёшь новый модуль src/core/name_numerology.py:
pythonLETTER_VALUES = {
    "а": 1, "б": 2, "в": 3, "г": 4, "д": 5,
    # ... весь алфавит
}

def name_number(name: str) -> int:
    digits = [LETTER_VALUES.get(c.lower(), 0) for c in name]
    total = sum(digits)
    while total > 9:
        total = sum(int(d) for d in str(total))
    return total
Шаг 2. Подключаешь в profile
В src/core/profile.py добавляешь:
pythonfrom .name_numerology import name_number

def build_person_profile(...):
    # ... существующий код
    profile["numerology"]["name_number"] = name_number(name)
    return profile
Шаг 3. (Опционально) Используешь в шаблонах
В любом из шаблонов теперь доступно {{ data.numerology.name_number }}.
Этот шаг необязательный — даже если ты не используешь это поле в HTML, оно попадёт в JSON для LLM, и модель сможет упоминать «вибрационный код имени» в текстах. Это самый дешёвый способ дать LLM новую информацию.
Что важно: через core ты добавляешь данные сразу во все три типа отчётов. Если хочешь — только в один, делай в src/reports/{type}_report.py в функции build_target_input.

Уровень 4: Добавить новый тип отчёта целиком
Допустим, хочешь сделать отчёт «Здоровье».
Шаг 1. Создай файл src/reports/health_report.py
Скопируй структуру money_report.py как шаблон. Поменяй:

REPORT_TYPE = "health"
TEMPLATE_NAME = "health_report.html.jinja"
EXAMPLES_SUBDIR = "health"
SYSTEM_PROMPT — под медицинский/велнес тон
REQUIRED_STRUCTURE — свои блоки
build_target_input — что именно вычислять (можно добавить health_dynamics)
generate — как обычно

Шаг 2. Создай шаблон
src/templates/health_report.html.jinja — берёшь любой существующий как образец, меняешь блоки.
Шаг 3. Создай эталон
examples/health/reference_blocks.json — пишешь полный пример отчёта для какого-то тестового человека.
Шаг 4. Подключи в API
В src/api.py:
pythonfrom .reports import self_report, couple_report, money_report, health_report

def generate_report(report_type, ...):
    # ... existing
    elif report_type == "health":
        return health_report.generate(...)
В src/cli.py добавь "health" в choices.
Шаг 5. (Опционально) Свой расчётный модуль
Если для нового отчёта нужны специальные числа — создай src/core/health_dynamics.py по аналогии с money_dynamics.py.
Шаг 6. Тест
В test_all.py добавь функцию test_health().
Запусти python test_all.py — если всё рендерится, новый отчёт работает.

Принцип, который стоит запомнить
Текст блока      → правишь reference_blocks.json
Структура блока  → reference_blocks.json + validator + шаблон
Расчёт чисел     → core/* + (опционально) подключение в profile
Новый отчёт      → src/reports/X.py + шаблон + эталон + api.py
Чем выше уровень — тем больше файлов меняешь.
Уровень 1 занимает 5 минут. Уровень 4 — пару часов, если есть готовые тексты эталона.

Несколько практических правил
1. Эталон важнее промпта. Не пытайся улучшать качество отчёта правкой системного промпта — переписывай эталон. LLM копирует стиль примера сильнее, чем следует инструкциям.
2. Не меняй имена ключей без необходимости. Если переименуешь points в items где-то в эталоне, забыв обновить шаблон — отчёт сломается. Имена ключей — контракт между всеми тремя слоями.
3. Списки в JSON всегда называй points. Это конвенция. items — зарезервированное слово в Jinja2 (метод dict), будет конфликт.
4. Если LLM ломает структуру — посмотри /tmp/llm_raw_response.txt. Туда сохраняется последний битый ответ. Часто там видно, что модель не поняла какую-то часть схемы — обычно лечится более явным эталоном.
5. Тестируй на 3-5 разных датах. Один тест на Артёме (число пути 8) не покажет, как отчёт работает для других чисел. Возьми ещё пару тестовых людей с другими числами и проверь.
6. Если расширяешь шаблон — следи за версткой на мобильном. В шаблонах есть @media (max-width: 680px) блок. Добавляя новый раздел, проверь что он не ломается на узком экране.
Если конкретный сценарий — скажи, какой именно, покажу пошагово на нём.