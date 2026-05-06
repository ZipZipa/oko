"""
Money report: денежный портрет одного человека.
10 блоков от обзора до момента смены работы.
"""
import json
from pathlib import Path

from ..core.profile import build_person_profile
from ..core.money_dynamics import full_money_profile
from ..core.llm_client import generate_blocks
from ..core.renderer import render_template


REPORT_TYPE = "money"
TEMPLATE_NAME = "money_report.html.jinja"
EXAMPLES_SUBDIR = "money"


SYSTEM_PROMPT = """Ты — автор персональных финансовых отчётов в стиле luxury minimal на русском языке.

ТОН:
- Холодный, точный, без обещаний богатства
- Прямые наблюдения о паттернах и блоках
- Не давай инвестиционных советов и не называй конкретные суммы

ОБЯЗАТЕЛЬНЫЕ ПРАВИЛА:
1. Все числа уже посчитаны. НЕ ПЕРЕСЧИТЫВАЙ.
2. Архетип, денежный код, потолок — даны в JSON, используй как факты.
3. Обращение — на "ты". Имя НЕ упоминай.
4. В блоках с финальной строкой — одно жёсткое предложение-вывод.

СТРОГО ДЛЯ БЛОКА «ДЕНЬГИ ПО ЛАДОНИ»:
- Реальной хиромантии нет (нет фото ладоней)
- Анализируй через черты лица как косвенные индикаторы
- Не выдумывай конкретные линии («линия Меркурия», «холм Юпитера» — НЕЛЬЗЯ)

СТРОГО ПРО ПРОГНОЗ:
- Используй ТОЛЬКО годы из forecast в JSON
- Опирайся на personal_year и tone каждого года
- Не называй конкретных сумм или процентов
- Описывай ХАРАКТЕР года, не предсказывай события

СТРУКТУРА ВЫХОДА:
Только валидный JSON. Без обёрток. Списки = "points".
"""


def _strip_photo_url(data: dict) -> dict:
    """Убирает photo_url из данных — LLM не видит фото,
    а base64-строка только расходует токены."""
    d = dict(data)
    if "user" in d:
        d["user"] = {k: v for k, v in d["user"].items() if k != "photo_url"}
    return d


def build_user_prompt(reference_blocks: dict, target_input: dict) -> str:
    target_input = _strip_photo_url(target_input)
    return f"""ЭТАЛОННЫЙ ПРИМЕР:
{json.dumps(reference_blocks, ensure_ascii=False, indent=2)}

═══════════════════════════════════════

ТВОЯ ЗАДАЧА

Сгенерируй JSON для нового пользователя. Те же ключи, та же глубина.
Учти его число пути, денежный код, текущий пинакл, прогноз по годам, черты лица.

Не копируй дословно.

ВХОД:
{json.dumps(target_input, ensure_ascii=False, indent=2)}

Верни только JSON."""


REQUIRED_STRUCTURE = {
    "overview": ["verdict_quote", "summary", "wealth_potential", "money_relationship"],
    "palmistry_money": ["intro_quote", "hand_pattern", "money_grip", "key_signs"],
    "main_problem": ["intro_quote", "name", "points", "root_cause", "manifestations", "final_line"],
    "money_code": ["intro_quote", "code_essence", "how_it_works", "blockers"],
    "ceiling": ["intro_quote", "current_level", "natural_zone", "what_lifts_it", "what_keeps_low", "final_line"],
    "earning_strategy": ["intro_quote", "natural_path", "do_more", "stop_doing", "best_fields"],
    "forecast": ["intro_quote", "years"],
    "money_sphere": ["intro_quote", "energy_type", "what_attracts", "what_repels", "ritual_pattern"],
    "anchor": ["intro_quote", "name", "origin", "how_it_blocks", "what_dissolves_it", "final_line"],
    "career_change": ["intro_quote", "current_phase", "best_window", "warning_periods", "signs_to_act"],
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
    years = blocks.get("forecast", {}).get("years")
    if years is not None and not isinstance(years, list):
        errors.append("forecast.years must be list")
    return errors


def build_target_input(face_data: dict, name: str, birthdate: str,
                       ref_year: int = None) -> dict:
    profile = build_person_profile(
        face_data, name, birthdate, ref_year=ref_year, include_scores=False,
    )
    profile["money"] = full_money_profile(
        birthdate, profile["numerology"]["life_path"], ref_year,
    )
    return profile


def generate(face_data: dict, name: str, birthdate: str,
             examples_dir: Path, templates_dir: Path,
             ref_year: int = None, model: str = None) -> str:
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
