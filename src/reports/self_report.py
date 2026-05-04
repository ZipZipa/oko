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

КРИТИЧНО ДЛЯ БЛОКА "АНАЛИЗ ВНЕШНОСТИ":
- Каждый пункт ДОЛЖЕН ссылаться на конкретное поле из features или scores
- НЕ упоминай: кожу, поры, морщины, отёчность, тон кожи, сияние
- НЕ упоминай: волосы, бороду, щетину, стрижку, причёску
- НЕ упоминай: телосложение, осанку, % жира
- Пиши только про: форму лица, глаза, нос, губы, брови, скулы, челюсть, лоб, симметрию

СТРУКТУРА ВЫХОДА:
Возвращай ТОЛЬКО валидный JSON по схеме из примера.
Без обёрток ```json```.
Списки пунктов называются "points" (не "items").
"""


def build_user_prompt(reference_blocks: dict, target_input: dict) -> str:
    return f"""ЭТАЛОННЫЙ ПРИМЕР ВЫХОДА (стиль, тон, структура):
{json.dumps(reference_blocks, ensure_ascii=False, indent=2)}

═══════════════════════════════════════

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


def validate_blocks(blocks: dict) -> list[str]:
    errors = []
    for top, fields in REQUIRED_STRUCTURE.items():
        if top not in blocks:
            errors.append(f"Missing top-level: {top}")
            continue
        for f in fields:
            if f not in blocks[top]:
                errors.append(f"Missing: {top}.{f}")
    return errors


# ═══ ГЛАВНАЯ ФУНКЦИЯ ═══

def build_target_input(face_data: dict, name: str, birthdate: str,
                       ref_year: int = None) -> dict:
    """Для self отчёта — просто профиль одного человека."""
    return build_person_profile(face_data, name, birthdate, ref_year=ref_year)


def generate(face_data: dict, name: str, birthdate: str,
             examples_dir: Path, templates_dir: Path,
             ref_year: int = None, model: str = None) -> str:
    """Генерирует self отчёт и возвращает HTML."""
    target = build_target_input(face_data, name, birthdate, ref_year)

    examples_subdir = examples_dir / EXAMPLES_SUBDIR
    with open(examples_subdir / "reference_blocks.json", encoding="utf-8") as f:
        ref_blocks = json.load(f)

    user_msg = build_user_prompt(ref_blocks, target)
    messages = [{"role": "user", "content": user_msg}]

    kwargs = {}
    if model:
        kwargs["model"] = model
    blocks = generate_blocks(SYSTEM_PROMPT, messages, validate_blocks, **kwargs)

    return render_template(templates_dir, TEMPLATE_NAME, target, blocks)
