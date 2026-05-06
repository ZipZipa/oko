"""
Self report: персональный портрет одного человека.
Анализ внешности + физиогномика + нумерология + матрица + глубинный анализ.
"""
import json
from pathlib import Path

from ..core.profile import build_person_profile
from ..core.llm_client import generate_blocks
from ..core.renderer import render_template


REPORT_TYPE = "self"
TEMPLATE_NAME = "self_report.html.jinja"
EXAMPLES_SUBDIR = "self"


# ═══ ПРОМПТ ═══

SYSTEM_PROMPT = """Ты — автор персональных отчётов в стиле luxury minimal на русском языке.

ТОН:
- Холодный, точный, без лести и не льстивый
- Прямые наблюдения, не эзотерические штампы
- Уровень "психологического портрета", а не "гороскопа"

ОБЯЗАТЕЛЬНЫЕ ПРАВИЛА:
1. Все числа уже посчитаны и переданы в JSON. НЕ ПЕРЕСЧИТЫВАЙ их.
2. Все характеристики лица переданы в JSON. НЕ ВЫДУМЫВАЙ другие.
3. Возраст уже посчитан.
4. Обращение — на "ты".
5. Имя пользователя в текстах НЕ упоминай — отчёт во втором лице.
6. В блоках с финальной строкой — одно жёсткое предложение-вывод.
7. Не используй эмоджи.

КРИТИЧНО ДЛЯ БЛОКА "АНАЛИЗ ВНЕШНОСТИ":
- Каждый пункт ДОЛЖЕН ссылаться на конкретное поле из features, scores или face_signals
- НЕ упоминай кожу, тон, поры, морщины — это идёт в отдельный блок grooming_and_style
- НЕ упоминай: волосы, бороду, щетину, стрижку, причёску
- НЕ упоминай: телосложение, осанку, % жира
- Пиши про: форму лица, глаза, нос, губы, брови, скулы, челюсть, лоб, симметрию
- ОБЯЗАТЕЛЬНО используй face_signals для углубления анализа:
  • emotional_profile — доминирующая эмоция и топ-3 — показывают эмоциональный фон человека
  • muscle_patterns — мышечные паттерны лица (сжатые губы, нахмур бровей и т.д.) — показывают привычные состояния
  • skin_signals — зоны напряжения лица — показывают, где накапливается стресс
  • asymmetry_signals — асимметрия черт — показывают разницу между публичным и внутренним лицом
  • stylistic_markers — серьги, пирсинг — маркеры самовыражения
  Эти сигналы — НЕ внешность, а ПСИХОЛОГИЧЕСКИЙ СЛЕД на лице. Используй их в блоках deep_portrait и physiognomy.

КРИТИЧНО ДЛЯ HAND_SIGNALS (если переданы):
- hand_signals — анализ ладони по линиям и форме руки
- Используй их для блоков hand_analysis и deep_portrait.block_2_hiromantia
- line_patterns — жизненная линия, голова, сердце, судьба: поля length, branching, strength_label, nuances
- key_line_pattern — какая линия выделяется на фоне остальных и её интерпретация
- element_type — стихия руки (earth/air/water/fire), palm_shape, description
- dominant_finger — доминирующий палец и его тема; thumb_angle — описание раскрыва большого пальца
- ratio_2d4d — соотношение указательного к безымянному пальцу: label + interpretation
- spread_and_curvature — spread_summary (разводка пальцев), curvature (кривизна каждого пальца)
- skin_contrast — контраст текстуры ладони и лица: только поле interpretation
- Эти сигналы ДОПОЛНЯЮТ face_signals и numerology, создавая более полный портрет

КРИТИЧНО ДЛЯ БЛОКА "HAND_ANALYSIS":
- Анализ руки — аналог beauty + physiognomy, но для ладони
- Обязательно ссылайся на hand_signals (element_type, dominant_finger, ratio_2d4d, line_patterns)
- hand_features — каждое поле (shape/fingers/thumb/mounts) должно быть объектом {"label": ..., "desc": ...}
- line_observations — по одному пункту на каждую линию, используй length/branching/strength_label/nuances из line_patterns
- Если hand_signals не переданы — НЕ создавай блоки hand_analysis и deep_portrait.block_2_hiromantia

КРИТИЧНО ДЛЯ БЛОКА "GROOMING_AND_STYLE":
- Источник данных: grooming_signals (skin_condition, tension_zones, skin_signals, accessories, skin_contrast, grooming_level, skin_level)
- Структура: verdict_quote, current_impression, strengths, improvements, style_archetype, style_tags
- Пиши конкретно: что работает, что нет, что изменить. Не общий текст — конкретные рекомендации
- accessories — список аксессуаров. Если пуст — НЕ упоминай серьги, пирсинг и другие украшения

КРИТИЧНО ДЛЯ БЛОКА "DEEP_PORTRAIT.BLOCK_2_HIROMANTIA":
- Хиромантический блок внутри deep_portrait — углубление hand_analysis
- Используй hand_signals для интерпретации линий и формы руки
- Свяжи с нумерологией и матрицей судьбы — линии руки как подтверждение/дополнение чисел
- Структура: quote, points (по каждой линии + перекрёсток), final_line

СТРУКТУРА ВЫХОДА:
Возвращай ТОЛЬКО валидный JSON по схеме из примера.
Без обёрток ```json```.
Списки пунктов называются "points" (не "items").
"""


def build_user_prompt(reference_blocks: dict, target_input: dict,
                      has_palm: bool = False) -> str:
    source_map = """
ИСТОЧНИКИ БЛОКОВ (используй ТОЛЬКО указанные данные):
- beauty, physiognomy → features, scores, face_signals
- hand_analysis → hand_signals.element_type (element/palm_shape/description), hand_signals.dominant_finger (finger/theme/thumb_angle), hand_signals.ratio_2d4d (label/interpretation), hand_signals.spread_and_curvature (spread_summary/curvature), hand_signals.line_patterns (length/branching/strength_label/nuances)
- deep_portrait.block_2_hiromantia → hand_signals.line_patterns, hand_signals.key_line_pattern, hand_signals.element_type
- grooming_and_style → grooming_signals (skin_condition, tension_zones, skin_signals, accessories, skin_contrast, grooming_level, skin_level)
- numerology, matrix → numerology, matrix
- deep_portrait (остальные блоки) → face_signals, numerology, matrix
"""
    palm_note = ""
    if not has_palm:
        palm_note = """
ВНИМАНИЕ: palm_data НЕ передан — НЕ генерируй блоки hand_analysis и deep_portrait.block_2_hiromantia.
В deep_portrait вместо block_2_hiromantia поставь null.
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

ВХОД:
{json.dumps(target_input, ensure_ascii=False, indent=2)}

Верни только JSON выхода. Без обёрток, без комментариев."""


# ═══ ВАЛИДАТОР ═══

REQUIRED_STRUCTURE = {
    "beauty": ["verdict_quote", "attractiveness_type", "strengths", "weaknesses"],
    "hand_analysis": ["verdict_quote", "element_type", "hand_features", "line_observations", "strengths", "weaknesses"],
    "grooming_and_style": ["verdict_quote", "current_impression", "strengths", "improvements", "style_archetype", "style_tags"],
    "physiognomy": ["form_quote", "features", "form_observations", "three_zones"],
    "numerology": [
        "life_path_quote", "life_path_points", "life_path_tags",
        "day_points", "pinnacles_descriptions", "pinnacles_summary",
        "personal_year_points", "personal_year_tags",
    ],
    "matrix": ["intro_quote", "positions", "key_insights"],
    "deep_portrait": [
        "block_2_hiromantia", "block_1_personality", "block_3_periods", "block_4_mistake",
        "block_5_relationships", "block_6_scenarios",
        "block_7_karma_lesson", "block_8_hidden_talent", "block_9_hidden_truth",
    ],
    "summary": ["quote", "points", "tags"],
}


def validate_blocks(blocks: dict, has_palm: bool = False) -> list[str]:
    structure = dict(REQUIRED_STRUCTURE)
    if not has_palm:
        structure.pop("hand_analysis", None)
        if "deep_portrait" in structure:
            structure["deep_portrait"] = [
                f for f in structure["deep_portrait"]
                if f != "block_2_hiromantia"
            ]
    errors = []
    for top, fields in structure.items():
        if top not in blocks:
            errors.append(f"Missing top-level: {top}")
            continue
        for f in fields:
            if f not in blocks[top]:
                errors.append(f"Missing: {top}.{f}")
    return errors


# ═══ ГЛАВНАЯ ФУНКЦИЯ ═══

def build_target_input(face_data: dict, name: str, birthdate: str,
                       ref_year: int = None, palm_data: dict = None) -> dict:
    """Для self отчёта — просто профиль одного человека."""
    return build_person_profile(face_data, name, birthdate, ref_year=ref_year,
                                palm_data=palm_data)


def generate(face_data: dict, name: str, birthdate: str,
             examples_dir: Path, templates_dir: Path,
             ref_year: int = None, model: str = None,
             palm_data: dict = None) -> str:
    """Генерирует self отчёт и возвращает HTML."""
    target = build_target_input(face_data, name, birthdate, ref_year,
                                palm_data=palm_data)

    examples_subdir = examples_dir / EXAMPLES_SUBDIR
    with open(examples_subdir / "reference_blocks.json", encoding="utf-8") as f:
        ref_blocks = json.load(f)

    has_palm = palm_data is not None
    user_msg = build_user_prompt(ref_blocks, target, has_palm=has_palm)
    messages = [{"role": "user", "content": user_msg}]

    kwargs = {}
    if model:
        kwargs["model"] = model
    blocks = generate_blocks(
        SYSTEM_PROMPT, messages,
        lambda b: validate_blocks(b, has_palm=has_palm),
        **kwargs,
    )

    return render_template(templates_dir, TEMPLATE_NAME, target, blocks)
