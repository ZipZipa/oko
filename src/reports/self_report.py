"""
Self report: персональный портрет одного человека.
Анализ внешности + физиогномика + нумерология + матрица + глубинный анализ.
"""
import json
import logging
from pathlib import Path

from ..core.profile import build_person_profile, prepare_for_llm
from ..core.llm_client import generate_blocks
from ..core.renderer import render_template

log = logging.getLogger(__name__)


REPORT_TYPE = "self"
TEMPLATE_NAME = "self_report.html.jinja"
EXAMPLES_SUBDIR = "self"


# ═══ ПРОМПТ ═══

SYSTEM_PROMPT = """Ты — автор персональных отчётов в стиле luxury minimal на русском языке.

ТОН:
- Холодный, точный, без лести
- Прямые наблюдения, не эзотерические штампы
- Уровень психологического портрета, не гороскопа

ОБЯЗАТЕЛЬНЫЕ ПРАВИЛА:
1. Все числа уже посчитаны и переданы в JSON. НЕ ПЕРЕСЧИТЫВАЙ. Не показывай формулы и промежуточные вычисления.
2. Все характеристики лица переданы в JSON. Не выдумывай другие.
3. Обращение — на "ты". Имя в текстах не упоминай — только второе лицо.
4. В блоках с финальной строкой (final_line) — одно жёсткое предложение-вывод.
5. Не используй эмоджи.
6. Эталонный пример задаёт структуру и тон, но не потолок глубины. Каждый блок — максимально конкретен для данного человека.
7. Сквозные паттерны: если одна черта подтверждается в двух системах — назови её явно в deep_portrait как подтверждённый паттерн, не упоминай дважды по отдельности.
8. Если поле входного JSON пустое или null — не интерпретируй и не заполняй вымышленными данными.
9. Весь текст — ТОЛЬКО на русском языке. Перекрёстные ссылки строго по формату: "(подтверждается нумерология: ...)", "(подтверждается физиогномика: ...)", "(подтверждается матрица: ...)" и т.д.
10. Если системы противоречат друг другу — назови противоречие явно, не сглаживай.

БЛОК "beauty" — АНАЛИЗ ВНЕШНОСТИ:
- Источник: features, scores, face_signals
- Пиши про: форму лица, глаза, нос, губы, брови, скулы, челюсть, лоб, симметрию
- НЕ упоминай: кожу, тон, поры, морщины, волосы, бороду, телосложение, одежду
- Используй face_signals как психологический след на лице:
  • emotional_profile — эмоциональный фон, доминирующее состояние
  • muscle_patterns — привычные мышечные паттерны (зажатые губы, сведённые брови и т.д.)
  • asymmetry_signals — разница между публичным и внутренним лицом
  • stylistic_markers — аксессуары как маркеры самовыражения (только если есть)
- beauty.weaknesses ("Особенности"): НЕ недостатки и НЕ рекомендации. Нейтральные наблюдения о структурных чертах — как они считываются окружающими.

БЛОК "grooming_and_style" — СОСТОЯНИЕ И ЭНЕРГИЯ:
- Источник: grooming_signals.tension_zones, grooming_signals.skin_signals.tension_zones, grooming_signals.skin_level, grooming_signals.grooming_level
- Блок про внутреннее состояние, не про внешность
- РАЗРЕШЕНО: зоны усталости и напряжения на лице, сигналы стресса, уровень энергии
- ЗАПРЕЩЕНО: одежда, стрижка, борода, уход за кожей, косметика, описание кожных дефектов
- style_archetype — энергетический образ ("тихая сила", "концентрированное внимание")
- style_tags — слова состояния, не внешности
- improvements — только про восстановление ресурса (сон, режим, снятие напряжения)

БЛОК "hand_analysis" — АНАЛИЗ ЛАДОНЕЙ:
- Источник: hand_signals.left, hand_signals.right, hand_signals.comparison.insights
- Описывай ОБЕ руки — не обобщай в одну
- left_hand / right_hand — отдельные объекты: {"element_type": "...", "key_trait": "..."}
- hand_features — черты правой руки как текущей (shape/fingers/thumb/mounts)
- line_observations — по одному пункту на каждую линию, с различием между левой и правой

БЛОК "chiromancy" — ХИРОМАНТИЯ (верхний уровень JSON):
- Источник: hand_signals.left, hand_signals.right, hand_signals.comparison.insights
- Левая рука = врождённое. Правая = реализованное.
- Свяжи с нумерологией и матрицей — линии как подтверждение или опровержение чисел
- points: минимум один пункт сравнения left vs right для каждой из 4 линий
- final_line — одно жёсткое предложение-вывод

СТРУКТУРА ВЫХОДА:
Возвращай ТОЛЬКО валидный JSON по схеме из примера. Без обёрток ```json```.
"""


def _strip_photo_url(data: dict) -> dict:
    """Убирает photo_url из данных — LLM не видит фото,
    а base64-строка только расходует токены."""
    d = dict(data)
    if "user" in d:
        d["user"] = {k: v for k, v in d["user"].items() if k != "photo_url"}
    return d


def build_user_prompt(reference_blocks: dict, target_input: dict,
                      has_palm: bool = False) -> str:
    """has_palm=True означает что переданы ОБЕ ладони (left + right)."""
    target_input = prepare_for_llm(_strip_photo_url(target_input))
    source_map = """
ИСТОЧНИКИ БЛОКОВ (используй ТОЛЬКО указанные данные):
- beauty, physiognomy → features, scores, face_signals
- grooming_and_style → grooming_signals (tension_zones, skin_signals.tension_zones, skin_level, grooming_level)
- hand_analysis, chiromancy → hand_signals.left, hand_signals.right, hand_signals.comparison.insights
- numerology → numerology (life_path, day, pinnacles, personal_year)
- matrix → matrix (каждая позиция: число карты + её энергия → конкретное поведение человека)
- deep_portrait → face_signals, numerology, matrix + hand_signals если переданы
- deep_portrait.block_3_periods → numerology.pinnacles (age_start/age_end) + numerology.personal_year + matrix.Испытание + matrix.Реализация; каждый период — вопрос-триггер
- physiognomy.three_zones → три зоны лица: каждая = период жизни + доминирующая тема + поведенческое проявление (минимум 2 предложения)
- deep_portrait.block_9_hidden_truth → три points строго о разном: (1) что знает но не говорит, (2) страх который не называет, (3) скрытый ресурс
"""
    palm_note = ""
    if not has_palm:
        palm_note = """
ВНИМАНИЕ: palm_data НЕ передан — НЕ генерируй блоки hand_analysis и chiromancy.
Ключ chiromancy в выходном JSON ставь null.
"""
    return f"""ЭТАЛОННЫЙ ПРИМЕР ВЫХОДА (стиль, тон, структура):
{json.dumps(reference_blocks, ensure_ascii=False, indent=2)}

{source_map}
{palm_note}
═════════════════════════════════════════

ТВОЯ ЗАДАЧА

Сгенерируй такой же по структуре JSON для нового пользователя.
Используй те же имена ключей, ту же глубину вложенности, те же типы значений.

Тексты должны соответствовать ИМЕННО ЭТОМУ человеку — учти его число, арканы,
форму лица. Не копируй эталон дословно.

ТРЕБОВАНИЯ К ГЛУБИНЕ (обязательно):
- pinnacles_descriptions: каждый пиннакль — минимум 3 предложения: архетип периода + главное испытание + ощущение перехода
- matrix.positions зоны жизни (Деньги, Любовь, Здоровье, Миссия): число карты → её энергия → конкретное поведение в этой зоне. Не общие определения
- hand_analysis.line_observations: для каждой линии — напряжение между линиями, не просто описание одной
- beauty.strengths/weaknesses: каждый пункт заканчивается тем, как черта считывается окружающими
- deep_portrait.block_6_scenarios.summary: заканчивается одним конкретным действием для каждой сферы
- В каждом блоке минимум одна перекрёстная ссылка на другую систему: "(подтверждается [система]: [деталь])"
- summary.tags: формат парадокса через дефис — "Лидер-невидимка", "Строитель чужих систем"

ВХОД:
{json.dumps(target_input, ensure_ascii=False, indent=2)}

Верни только JSON выхода. Без обёрток, без комментариев."""


# ═══ ВАЛИДАТОР ═══

REQUIRED_STRUCTURE = {
    "beauty": ["verdict_quote", "attractiveness_type", "strengths", "weaknesses"],
    "hand_analysis": ["verdict_quote", "element_type", "hand_features", "line_observations", "strengths", "weaknesses"],
    "chiromancy": ["quote", "points", "final_line"],
    "grooming_and_style": ["verdict_quote", "current_impression", "strengths", "improvements", "style_archetype", "style_tags"],
    "physiognomy": ["form_quote", "features", "form_observations", "three_zones"],
    "numerology": [
        "life_path_quote", "life_path_points", "life_path_tags",
        "day_points", "pinnacles_descriptions", "pinnacles_summary",
        "personal_year_points", "personal_year_tags",
    ],
    "matrix": ["intro_quote", "positions", "key_insights"],
    "deep_portrait": [
        "block_1_personality", "block_3_periods", "block_4_mistake",
        "block_5_relationships", "block_6_scenarios",
        "block_7_karma_lesson", "block_8_hidden_talent", "block_9_hidden_truth",
    ],
    "summary": ["quote", "points", "tags"],
}


def validate_blocks(blocks: dict, has_palm: bool = False) -> list[str]:
    structure = dict(REQUIRED_STRUCTURE)
    if not has_palm:
        structure.pop("hand_analysis", None)
        structure.pop("chiromancy", None)
    errors = []
    for top, fields in structure.items():
        if top not in blocks:
            errors.append(f"Missing top-level: {top}")
            continue
        if blocks[top] is None:
            continue
        for f in fields:
            if f not in blocks[top]:
                errors.append(f"Missing: {top}.{f}")
    return errors


# ═══ ГЛАВНАЯ ФУНКЦИЯ ═══

def build_target_input(face_data: dict, name: str, birthdate: str,
                       ref_year: int = None,
                       palm_data_left: dict = None,
                       palm_data_right: dict = None) -> dict:
    """Для self отчёта — просто профиль одного человека."""
    return build_person_profile(face_data, name, birthdate, ref_year=ref_year,
                                palm_data_left=palm_data_left,
                                palm_data_right=palm_data_right)


def _load_reference_blocks(reference: str) -> dict:
    if reference.strip().startswith("{"):
        return json.loads(reference)
    with open(reference, encoding="utf-8") as f:
        return json.load(f)


def _generate_palm_blocks(target: dict, ref_hand_analysis: dict, ref_chiromancy: dict,
                          model: str = None,
                          telegram_id: int | None = None) -> dict:
    """Точечный LLM-вызов: только hand_analysis + chiromancy."""
    ha_fields = REQUIRED_STRUCTURE["hand_analysis"]
    ch_fields = REQUIRED_STRUCTURE["chiromancy"]

    def validate_fn(blocks):
        errors = []
        for section, fields in [("hand_analysis", ha_fields), ("chiromancy", ch_fields)]:
            if section not in blocks:
                errors.append(f"Missing top-level: {section}")
            else:
                errors += [f"Missing: {section}.{f}" for f in fields if f not in blocks[section]]
        return errors

    user_msg = f"""Эталонный пример блоков hand_analysis и chiromancy:
{json.dumps({"hand_analysis": ref_hand_analysis, "chiromancy": ref_chiromancy}, ensure_ascii=False, indent=2)}

ЗАДАЧА: сгенерируй блоки "hand_analysis" и "chiromancy" для нового пользователя.
- Используй hand_signals.left, hand_signals.right, hand_signals.comparison.insights
- Левая рука = врождённое, правая = реализованное
- В chiromancy.points — минимум один пункт сравнения left vs right для каждой из 4 линий
- Свяжи с нумерологией и матрицей судьбы из входных данных
- final_line — одно жёсткое предложение-вывод

Данные пользователя:
{json.dumps(prepare_for_llm(target), ensure_ascii=False, indent=2)}

Верни ТОЛЬКО JSON вида:
{{"hand_analysis": {{...}}, "chiromancy": {{...}}}}
Без обёрток, без комментариев."""

    kwargs = {}
    if model:
        kwargs["model"] = model
    return generate_blocks(SYSTEM_PROMPT, [{"role": "user", "content": user_msg}],
                            validate_fn, telegram_id=telegram_id, **kwargs)


def generate(face_data: dict, name: str, birthdate: str,
             examples_dir: Path, templates_dir: Path,
             ref_year: int = None, model: str = None,
             palm_data_left: dict = None,
             palm_data_right: dict = None,
             plan: str = "full",
             reference: str = None,
             _out_blocks: list = None,
             telegram_id: int | None = None) -> str:
    """Генерирует self отчёт и возвращает HTML.

    reference: путь к JSON-файлу с блоками ИЛИ сырая JSON-строка.
               Если указан — LLM не вызывается (кроме случая reference + has_palm:
               тогда точечно генерируются только hand_analysis и chiromancy).
    _out_blocks: если передан пустой список, в него будет добавлен dict blocks
                 после генерации через LLM (для сохранения в БД).
    telegram_id: Telegram ID пользователя — для логирования контекста (опционально).
    """
    _ctx = f"tg={telegram_id} " if telegram_id else ""
    log.info("%sself_report.generate: старт plan=%s reference=%s has_palm=%s",
             _ctx, plan, bool(reference),
             palm_data_left is not None and palm_data_right is not None)

    target = build_target_input(face_data, name, birthdate, ref_year,
                                palm_data_left=palm_data_left,
                                palm_data_right=palm_data_right)
    has_palm = palm_data_left is not None and palm_data_right is not None
    examples_subdir = examples_dir / EXAMPLES_SUBDIR

    # ── Референс + ладони: берём готовые блоки, точечно добавляем хиромантию ──
    if reference and has_palm:
        log.info("%sself_report: режим reference+palm (точечная генерация хиромантии)", _ctx)
        blocks = _load_reference_blocks(reference)
        with open(examples_subdir / "reference_blocks.json", encoding="utf-8") as f:
            ref_ex = json.load(f)
        palm_blocks = _generate_palm_blocks(
            target,
            ref_ex.get("hand_analysis", {}),
            ref_ex.get("chiromancy", {}),
            model=model,
            telegram_id=telegram_id,
        )
        blocks["hand_analysis"] = palm_blocks["hand_analysis"]
        blocks["chiromancy"] = palm_blocks["chiromancy"]
        errors = validate_blocks(blocks, has_palm=True)
        if errors:
            log.warning("%sПредупреждения валидации (reference + palm): %s", _ctx, errors)
        if _out_blocks is not None:
            _out_blocks.append(blocks)
        log.info("%sself_report: завершён (reference+palm)", _ctx)
        return render_template(templates_dir, TEMPLATE_NAME, target, blocks, plan=plan)

    # ── Референс без ладоней: только рендеринг ──
    if reference:
        log.info("%sself_report: режим reference-only (рендеринг без LLM)", _ctx)
        blocks = _load_reference_blocks(reference)
        errors = validate_blocks(blocks, has_palm=False)
        if errors:
            log.warning("%sПредупреждения валидации референса: %s", _ctx, errors)
        log.info("%sself_report: завершён (reference-only)", _ctx)
        return render_template(templates_dir, TEMPLATE_NAME, target, blocks, plan=plan)

    # ── Обычный режим: полный LLM ──
    log.info("%sself_report: режим full LLM", _ctx)
    with open(examples_subdir / "reference_blocks.json", encoding="utf-8") as f:
        ref_blocks = json.load(f)

    user_msg = build_user_prompt(ref_blocks, target, has_palm=has_palm)
    messages = [{"role": "user", "content": user_msg}]

    kwargs = {}
    if model:
        kwargs["model"] = model
    blocks = generate_blocks(
        SYSTEM_PROMPT, messages,
        lambda b: validate_blocks(b, has_palm=has_palm),
        telegram_id=telegram_id,
        **kwargs,
    )

    # Без ладоней — подставляем референсные блоки как заглушки для отображения замка
    if not has_palm:
        blocks.setdefault("hand_analysis", ref_blocks.get("hand_analysis"))
        blocks.setdefault("chiromancy", ref_blocks.get("chiromancy"))

    if _out_blocks is not None:
        _out_blocks.append(blocks)

    log.info("%sself_report: завершён (full LLM)", _ctx)
    return render_template(templates_dir, TEMPLATE_NAME, target, blocks, plan=plan)
