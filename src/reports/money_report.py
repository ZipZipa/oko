"""
Money report: денежный портрет одного человека.
10 блоков от обзора до момента смены работы.
"""
import json
import logging
from pathlib import Path

from ..core.profile import build_person_profile, prepare_for_llm
from ..core.money_dynamics import full_money_profile
from ..core.llm_client import generate_blocks
from ..core.renderer import render_template

log = logging.getLogger(__name__)


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
- Источник: hand_signals.left, hand_signals.right — анализируй линии применительно к деньгам и потокам ресурсов
- Левая рука = врождённый денежный потенциал, правая = реализованный

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


def build_user_prompt(reference_blocks: dict, target_input: dict,
                      has_palm: bool = False) -> str:
    target_input = prepare_for_llm(_strip_photo_url(target_input))
    palm_note = "" if has_palm else "\nВНИМАНИЕ: ладони НЕ переданы — НЕ генерируй блок palmistry_money, оставь ключ null.\n"
    source_map = """
ИСТОЧНИКИ БЛОКОВ (используй ТОЛЬКО указанные данные):
- overview → numerology.life_path, money.archetype, face_signals
- palmistry_money → hand_signals.left, hand_signals.right (линии применительно к деньгам и ресурсам)
- main_problem → money.archetype.typical_block, numerology, matrix
- money_code → money.code (number, formula, meaning)
- ceiling → money.ceiling_indicator, money.archetype, numerology.pinnacles
- earning_strategy → money.archetype (best_fields, earning_style), numerology.life_path
- forecast → money.forecast (каждый год: personal_year, tone)
- money_sphere → money.archetype, numerology.life_path, matrix
- anchor → money.archetype.typical_block, matrix, numerology
- career_change → money.forecast, numerology.personal_year, numerology.pinnacles
"""
    return f"""ЭТАЛОННЫЙ ПРИМЕР:
{json.dumps(reference_blocks, ensure_ascii=False, indent=2)}

{source_map}{palm_note}
═══════════════════════════════════════

ТВОЯ ЗАДАЧА

Сгенерируй JSON для нового пользователя. Те же ключи, та же глубина.
Учти его число пути, денежный код, текущий пиннакл, прогноз по годам, черты лица.
В каждом блоке минимум одна перекрёстная ссылка на другую систему.

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


def validate_blocks(blocks: dict, has_palm: bool = True) -> list[str]:
    structure = dict(REQUIRED_STRUCTURE)
    if not has_palm:
        structure.pop("palmistry_money", None)
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
    years = blocks.get("forecast", {}).get("years")
    if years is not None and not isinstance(years, list):
        errors.append("forecast.years must be list")
    return errors


def build_target_input(face_data: dict, name: str, birthdate: str,
                       ref_year: int = None,
                       palm_data_left: dict = None,
                       palm_data_right: dict = None) -> dict:
    profile = build_person_profile(
        face_data, name, birthdate, ref_year=ref_year, include_scores=False,
        palm_data_left=palm_data_left, palm_data_right=palm_data_right,
    )
    profile["money"] = full_money_profile(
        birthdate, profile["numerology"]["life_path"], ref_year,
    )
    return profile


def _load_reference_blocks(reference: str) -> dict:
    if reference.strip().startswith("{"):
        return json.loads(reference)
    with open(reference, encoding="utf-8") as f:
        return json.load(f)


def _generate_palmistry_block(target: dict, ref_palmistry: dict,
                              model: str = None) -> dict:
    """Точечный LLM-вызов: только palmistry_money на основе реальных ладоней."""
    pm_fields = REQUIRED_STRUCTURE["palmistry_money"]

    def validate_fn(blocks):
        if "palmistry_money" not in blocks:
            return ["Missing top-level: palmistry_money"]
        return [f"Missing: palmistry_money.{f}" for f in pm_fields if f not in blocks["palmistry_money"]]

    user_msg = f"""Эталонный пример блока palmistry_money:
{json.dumps({"palmistry_money": ref_palmistry}, ensure_ascii=False, indent=2)}

ЗАДАЧА: сгенерируй блок "palmistry_money" для нового пользователя.
- Источник: hand_signals.left, hand_signals.right, hand_signals.comparison.insights
- Левая рука = врождённый денежный потенциал, правая = реализованный
- Анализируй линии применительно к деньгам и потокам ресурсов
- Свяжи с numerology.life_path и money.archetype из входных данных

Данные пользователя:
{json.dumps(prepare_for_llm(target), ensure_ascii=False, indent=2)}

Верни ТОЛЬКО JSON вида:
{{"palmistry_money": {{...}}}}
Без обёрток, без комментариев."""

    kwargs = {}
    if model:
        kwargs["model"] = model
    return generate_blocks(SYSTEM_PROMPT, [{"role": "user", "content": user_msg}], validate_fn, **kwargs)


def generate(face_data: dict, name: str, birthdate: str,
             examples_dir: Path, templates_dir: Path,
             ref_year: int = None, model: str = None,
             palm_data_left: dict = None,
             palm_data_right: dict = None,
             plan: str = "full",
             reference: str = None,
             _out_blocks: list = None) -> str:
    """Генерирует money отчёт и возвращает HTML.

    reference: путь к JSON-файлу с блоками ИЛИ сырая JSON-строка.
               Если указан — LLM не вызывается.
    _out_blocks: если передан пустой список, в него будет добавлен dict blocks.
    """
    target = build_target_input(face_data, name, birthdate, ref_year,
                                palm_data_left=palm_data_left,
                                palm_data_right=palm_data_right)
    has_palm = palm_data_left is not None and palm_data_right is not None
    examples_subdir = examples_dir / EXAMPLES_SUBDIR

    # ── Референс + ладони: перегенерируем только palmistry_money ──
    if reference and has_palm:
        blocks = _load_reference_blocks(reference)
        with open(examples_subdir / "reference_blocks.json", encoding="utf-8") as f:
            ref_ex = json.load(f)
        palm_block = _generate_palmistry_block(
            target, ref_ex.get("palmistry_money", {}), model=model,
        )
        blocks["palmistry_money"] = palm_block["palmistry_money"]
        errors = validate_blocks(blocks)
        if errors:
            log.warning("Предупреждения валидации (reference + palm): %s", errors)
        if _out_blocks is not None:
            _out_blocks.append(blocks)
        return render_template(templates_dir, TEMPLATE_NAME, target, blocks, plan=plan)

    # ── Референс без ладоней: только рендеринг ──
    if reference:
        blocks = _load_reference_blocks(reference)
        errors = validate_blocks(blocks, has_palm=has_palm)
        if errors:
            log.warning("Предупреждения валидации (reference): %s", errors)
        return render_template(templates_dir, TEMPLATE_NAME, target, blocks, plan=plan)

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
        **kwargs,
    )

    if not has_palm:
        blocks.setdefault("palmistry_money", ref_blocks.get("palmistry_money"))

    if _out_blocks is not None:
        _out_blocks.append(blocks)

    return render_template(templates_dir, TEMPLATE_NAME, target, blocks, plan=plan)
