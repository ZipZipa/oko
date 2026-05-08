"""
Couple report: парный отчёт совместимости.
9 блоков от компатибилити до точки разрыва.
"""
import json
import sys
from pathlib import Path

from ..core.profile import build_person_profile, prepare_for_llm
from ..core.couple_dynamics import couple_full_dynamics
from ..core.face_dynamics import face_contrast, matrix_overlap
from ..core.llm_client import generate_blocks
from ..core.renderer import render_template


REPORT_TYPE = "couple"
TEMPLATE_NAME = "couple_report.html.jinja"
EXAMPLES_SUBDIR = "couple"


SYSTEM_PROMPT = """Ты — автор персональных отчётов о совместимости пар в стиле luxury minimal на русском языке.

ТОН:
- Холодный, точный, без розовых иллюзий
- Прямые наблюдения, не ванильные предсказания
- Имена пары используй естественно, не на каждом предложении

ОБЯЗАТЕЛЬНЫЕ ПРАВИЛА:
1. Все числа уже посчитаны и переданы в JSON. НЕ ПЕРЕСЧИТЫВАЙ их.
2. Имена А и Б в JSON — реальные имена.
3. НЕ ВЫДУМЫВАЙ кожу, бороду, волосы — этих данных нет.
4. В блоках "Измена", "Точка разрыва" — будь честным, но не алармистом.
5. В блоках с финальной строкой — одно жёсткое предложение-вывод.

КРИТИЧНО ПРОТИВ ГАЛЛЮЦИНАЦИЙ:
- Хиромантия — анализируй ТОЛЬКО по чертам лица (features), не выдумывай линии ладоней
- Семья/родительство — оцени по нумерологии и матрице, не предсказывай пол/количество детей. У пары УЖЕ МОГУТ БЫТЬ дети — учитывай это, не пиши будто детей нет или они только планируются.
- Карма — описывай уроки пары, не "прошлые жизни" с конкретикой
- Пинакли, личные года и календарные годы — возраста пинаклей (age_start/age_end) АБСОЛЮТНЫЕ (возраст человека), а годы в marriage_perspective ОТНОСИТЕЛЬНЫЕ (годы отношений). Ты НЕ ЗНАЕШЬ дату начала отношений. НЕ привязывай пинакли к годам брака — НЕ пиши «у N начинается пинакль X на Y-м году». НЕ называй конкретные календарные годы (2031, 2034 и т.д.) — ты не знаешь текущий год отношений. Это галлюцинация. Применимо ко ВСЕМ блокам, не только marriage_perspective.

СТРУКТУРА ВЫХОДА:
Возвращай ТОЛЬКО валидный JSON по схеме из примера.
Без обёрток ```json```. Списки = "points".
"""


def _strip_photo_url(data: dict) -> dict:
    """Убирает photo_url из данных — LLM не видит фото,
    а base64-строка только расходует токены."""
    d = dict(data)
    for key in ("person_a", "person_b"):
        if key in d and "user" in d[key]:
            d[key] = dict(d[key])
            d[key]["user"] = {k: v for k, v in d[key]["user"].items() if k != "photo_url"}
    return d


def build_user_prompt(reference_blocks: dict, target_input: dict) -> str:
    target_input = prepare_for_llm(_strip_photo_url(target_input))
    source_map = """
ИСТОЧНИКИ БЛОКОВ (используй ТОЛЬКО указанные данные):
- compatibility → couple.compatibility (score, type), couple.matrix_overlap, couple.union_number, couple.year_sync
- palmistry_heart → person_a.features, person_b.features (косвенные индикаторы — реальных ладоней нет)
- fidelity → person_a.numerology, person_b.numerology, person_a.matrix, person_b.matrix, couple.face_contrast
- marriage_perspective → couple.compatibility, couple.union_number, person_a.numerology.personal_year, person_b.numerology.personal_year
- karma → couple.matrix_overlap, person_a.matrix, person_b.matrix, couple.union_number
- wealth → person_a.numerology.life_path, person_b.numerology.life_path, couple.compatibility
- family → person_a.numerology, person_b.numerology, couple.age (семья и родительство — учитывай что у пары уже могут быть дети)
- duration → couple.compatibility, couple.age, couple.year_sync, couple.matrix_overlap
- breaking_point → couple.face_contrast, couple.year_sync, couple.compatibility
"""
    return f"""ЭТАЛОННЫЙ ПРИМЕР ВЫХОДА:
{json.dumps(reference_blocks, ensure_ascii=False, indent=2)}

{source_map}
═══════════════════════════════════════

ТВОЯ ЗАДАЧА

Сгенерируй JSON для НОВОЙ пары. Те же ключи, та же структура.
Учти: числа жизненного пути и совместимость, арканы матриц, разницу возрастов,
контраст лиц, синхронность личных годов, число союза.
В каждом блоке — минимум одна перекрёстная ссылка на другую систему.

Не копируй эталон дословно.

ВХОД:
{json.dumps(target_input, ensure_ascii=False, indent=2)}

Верни только JSON."""


REQUIRED_STRUCTURE = {
    "compatibility": ["verdict_quote", "summary", "strengths", "weaknesses",
                      "compatibility_score", "matrix_resonance"],
    "palmistry_heart": ["intro_quote", "person_a_pattern", "person_b_pattern",
                        "match_dynamic"],
    "fidelity": ["intro_quote", "person_a_risk", "person_b_risk",
                 "trigger_situations", "stabilizing_factors"],
    "marriage_perspective": ["intro_quote", "years"],
    "karma": ["intro_quote", "lesson_for_pair", "lesson_a", "lesson_b",
              "final_line"],
    "wealth": ["intro_quote", "level", "points", "money_pattern",
               "blocking_factors"],
    "family": ["intro_quote", "potential_level", "points", "timing"],
    "duration": ["intro_quote", "type", "summary", "factors_extending",
                 "factors_shortening"],
    "breaking_point": ["intro_quote", "probability", "trigger", "timing",
                       "preventable_by", "final_line"],
}

NESTED_REQUIREMENTS = {
    "fidelity.person_a_risk": ["level", "desc"],
    "fidelity.person_b_risk": ["level", "desc"],
}


def _get_nested(d: dict, path: str):
    cur = d
    for p in path.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def validate_blocks(blocks: dict) -> list[str]:
    errors = []
    for top, fields in REQUIRED_STRUCTURE.items():
        if top not in blocks:
            errors.append(f"Missing top-level: {top}")
            continue
        for f in fields:
            if f not in blocks[top]:
                errors.append(f"Missing: {top}.{f}")
    for path, fields in NESTED_REQUIREMENTS.items():
        node = _get_nested(blocks, path)
        if node is None:
            errors.append(f"Missing nested: {path}")
            continue
        for f in fields:
            if f not in node:
                errors.append(f"Missing: {path}.{f}")
    years = _get_nested(blocks, "marriage_perspective.years")
    if years is not None and not isinstance(years, list):
        errors.append("marriage_perspective.years must be list")
    return errors


def build_target_input(face_a: dict, name_a: str, birthdate_a: str,
                       face_b: dict, name_b: str, birthdate_b: str,
                       ref_year: int = None) -> dict:
    person_a = build_person_profile(
        face_a, name_a, birthdate_a, ref_year=ref_year,
        include_scores=False, include_matrix_raw=True,
    )
    person_b = build_person_profile(
        face_b, name_b, birthdate_b, ref_year=ref_year,
        include_scores=False, include_matrix_raw=True,
    )

    couple = couple_full_dynamics(
        birthdate_a, birthdate_b,
        person_a["numerology"]["life_path"],
        person_b["numerology"]["life_path"],
        person_a["numerology"]["personal_year"]["number"],
        person_b["numerology"]["personal_year"]["number"],
    )
    couple["face_contrast"] = face_contrast(person_a["features"], person_b["features"])
    couple["matrix_overlap"] = matrix_overlap(person_a["matrix_raw"], person_b["matrix_raw"])

    person_a.pop("matrix_raw", None)
    person_b.pop("matrix_raw", None)

    return {"person_a": person_a, "person_b": person_b, "couple": couple}


def _load_reference_blocks(reference: str) -> dict:
    if reference.strip().startswith("{"):
        return json.loads(reference)
    with open(reference, encoding="utf-8") as f:
        return json.load(f)


def generate(face_a: dict, name_a: str, birthdate_a: str,
             face_b: dict, name_b: str, birthdate_b: str,
             examples_dir: Path, templates_dir: Path,
             ref_year: int = None, model: str = None,
             plan: str = "full",
             reference: str = None,
             _out_blocks: list = None) -> str:
    """Генерирует couple отчёт и возвращает HTML.

    reference: путь к JSON-файлу с блоками ИЛИ сырая JSON-строка.
               Если указан — LLM не вызывается.
    _out_blocks: если передан пустой список, в него будет добавлен dict blocks.
    """
    target = build_target_input(
        face_a, name_a, birthdate_a,
        face_b, name_b, birthdate_b, ref_year,
    )
    examples_subdir = examples_dir / EXAMPLES_SUBDIR

    if reference:
        blocks = _load_reference_blocks(reference)
        errors = validate_blocks(blocks)
        if errors:
            print("Предупреждения валидации (reference):", file=sys.stderr)
            for e in errors:
                print(f"  • {e}", file=sys.stderr)
        return render_template(templates_dir, TEMPLATE_NAME, target, blocks, plan=plan)

    with open(examples_subdir / "reference_blocks.json", encoding="utf-8") as f:
        ref_blocks = json.load(f)

    user_msg = build_user_prompt(ref_blocks, target)
    messages = [{"role": "user", "content": user_msg}]

    kwargs = {}
    if model:
        kwargs["model"] = model
    blocks = generate_blocks(SYSTEM_PROMPT, messages, validate_blocks, **kwargs)

    if _out_blocks is not None:
        _out_blocks.append(blocks)

    return render_template(templates_dir, TEMPLATE_NAME, target, blocks, plan=plan)
