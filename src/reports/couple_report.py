"""
Couple report: парный отчёт совместимости.
9 блоков от компатибилити до точки разрыва.
"""
import json
import logging
from pathlib import Path

from ..core.profile import build_person_profile, prepare_for_llm
from ..core.couple_dynamics import couple_full_dynamics
from ..core.face_dynamics import face_contrast, matrix_overlap
from ..core.llm_client import generate_blocks
from ..core.renderer import render_template

log = logging.getLogger(__name__)


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
- Хиромантия — анализируй ТОЛЬКО по линиям ладоней (palm_left/palm_right). Левая рука = врождённое, правая = реализованное. Если ладони не переданы — НЕ генерируй блок palmistry_heart (верни null). НЕ используй черты лица (features) для хиромантии — это отдельная система.
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


def build_user_prompt(reference_blocks: dict, target_input: dict,
                      has_palm: bool = False) -> str:
    target_input = prepare_for_llm(_strip_photo_url(target_input))
    palm_note = "" if has_palm else "\nВНИМАНИЕ: ладони НЕ переданы — НЕ генерируй блок palmistry_heart, оставь ключ null.\n"
    source_map = """
ИСТОЧНИКИ БЛОКОВ (используй ТОЛЬКО указанные данные):
- compatibility → couple.compatibility (score, type), couple.matrix_overlap, couple.union_number, couple.year_sync
- palmistry_heart → person_a.palm_left/palm_right, person_b.palm_left/palm_right (ТОЛЬКО линии ладоней; если ладони не переданы — блок null, НЕ использовать features)
- fidelity → person_a.numerology, person_b.numerology, person_a.matrix, person_b.matrix, couple.face_contrast
- marriage_perspective → couple.compatibility, couple.union_number, person_a.numerology.personal_year, person_b.numerology.personal_year
- karma → couple.matrix_overlap, person_a.matrix, person_b.matrix, couple.union_number
- wealth → person_a.numerology.life_path, person_b.numerology.life_path, couple.compatibility
- family → person_a.numerology, person_b.numerology, couple.age (семья и родительство — учитывай что у пары уже могут быть дети)
- duration → couple.compatibility, couple.age, couple.year_sync, couple.matrix_overlap
- breaking_point → couple.face_contrast, couple.year_sync, couple.compatibility
- sexual_compatibility → person_a.features, person_b.features, person_a.numerology, person_b.numerology, couple.compatibility, couple.face_contrast
- perception → person_a.features, person_b.features, person_a.numerology, person_b.numerology, couple.face_contrast, couple.compatibility
"""
    return f"""ЭТАЛОННЫЙ ПРИМЕР ВЫХОДА:
{json.dumps(reference_blocks, ensure_ascii=False, indent=2)}

{source_map}{palm_note}
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
    "sexual_compatibility": ["intro_quote", "person_a_style", "person_b_style",
                             "dynamic", "tension_points", "final_line"],
    "perception": ["intro_quote", "how_a_sees_b", "how_b_sees_a",
                   "blind_spots", "final_line"],
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


def validate_blocks(blocks: dict, has_palm: bool = False) -> list[str]:
    structure = dict(REQUIRED_STRUCTURE)
    if not has_palm:
        structure.pop("palmistry_heart", None)
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
                       ref_year: int = None,
                       palm_data_a_left: dict = None,
                       palm_data_a_right: dict = None,
                       palm_data_b_left: dict = None,
                       palm_data_b_right: dict = None) -> dict:
    person_a = build_person_profile(
        face_a, name_a, birthdate_a, ref_year=ref_year,
        include_scores=False, include_matrix_raw=True,
    )
    person_b = build_person_profile(
        face_b, name_b, birthdate_b, ref_year=ref_year,
        include_scores=False, include_matrix_raw=True,
    )

    # Добавляем данные ладоней, если есть
    if palm_data_a_left:
        person_a["palm_left"] = palm_data_a_left
    if palm_data_a_right:
        person_a["palm_right"] = palm_data_a_right
    if palm_data_b_left:
        person_b["palm_left"] = palm_data_b_left
    if palm_data_b_right:
        person_b["palm_right"] = palm_data_b_right

    couple = couple_full_dynamics(
        birthdate_a, birthdate_b,
        person_a["numerology"]["life_path"],
        person_b["numerology"]["life_path"],
        person_a["numerology"]["personal_year"]["number"],
        person_b["numerology"]["personal_year"]["number"],
    )
    couple["face_contrast"] = face_contrast(person_a["features"], person_b["features"])
    couple["matrix_overlap"] = matrix_overlap(person_a["matrix_raw"], person_b["matrix_raw"])

    # Отмечаем наличие ладоней для промпта
    couple["has_palms_a"] = bool(palm_data_a_left or palm_data_a_right)
    couple["has_palms_b"] = bool(palm_data_b_left or palm_data_b_right)

    person_a.pop("matrix_raw", None)
    person_b.pop("matrix_raw", None)

    return {"person_a": person_a, "person_b": person_b, "couple": couple}


def _load_reference_blocks(reference: str) -> dict:
    if reference.strip().startswith("{"):
        return json.loads(reference)
    with open(reference, encoding="utf-8") as f:
        return json.load(f)


def _generate_palmistry_heart_block(target: dict, ref_palmistry: dict,
                                    model: str = None,
                                    telegram_id: int | None = None) -> dict:
    """Точечный LLM-вызов: только palmistry_heart на основе реальных ладоней."""
    ph_fields = REQUIRED_STRUCTURE["palmistry_heart"]

    def validate_fn(blocks):
        if "palmistry_heart" not in blocks:
            return ["Missing top-level: palmistry_heart"]
        return [f"Missing: palmistry_heart.{f}" for f in ph_fields if f not in blocks["palmistry_heart"]]

    user_msg = f"""Эталонный пример блока palmistry_heart:
{json.dumps({"palmistry_heart": ref_palmistry}, ensure_ascii=False, indent=2)}

ЗАДАЧА: сгенерируй блок "palmistry_heart" для новой пары.
- Источник: person_a.palm_left/palm_right, person_b.palm_left/palm_right
- Левая рука = врождённое, правая = реализованное
- Анализируй линии применительно к любви и эмоциям
- Свяжи с numerology.life_path и couple.compatibility из входных данных

Данные пары:
{json.dumps(prepare_for_llm(target), ensure_ascii=False, indent=2)}

Верни ТОЛЬКО JSON вида:
{{"palmistry_heart": {{...}}}}
Без обёрток, без комментариев."""

    kwargs = {}
    if model:
        kwargs["model"] = model
    return generate_blocks(SYSTEM_PROMPT, [{"role": "user", "content": user_msg}],
                            validate_fn, telegram_id=telegram_id, **kwargs)


def generate(face_a: dict, name_a: str, birthdate_a: str,
             face_b: dict, name_b: str, birthdate_b: str,
             examples_dir: Path, templates_dir: Path,
             ref_year: int = None, model: str = None,
             palm_data_a_left: dict = None,
             palm_data_a_right: dict = None,
             palm_data_b_left: dict = None,
             palm_data_b_right: dict = None,
             plan: str = "full",
             reference: str = None,
             _out_blocks: list = None,
             telegram_id: int | None = None) -> str:
    """Генерирует couple отчёт и возвращает HTML.

    palm_data_a_left/right — данные ладоней пользователя A.
    palm_data_b_left/right — данные ладоней партнёра B.
    reference: путь к JSON-файлу с блоками ИЛИ сырая JSON-строка.
               Если указан — LLM не вызывается.
    _out_blocks: если передан пустой список, в него будет добавлен dict blocks.
    telegram_id: Telegram ID пользователя — для логирования контекста (опционально).
    """
    _ctx = f"tg={telegram_id} " if telegram_id else ""
    log.info("%scouple_report.generate: старт plan=%s reference=%s has_palm=%s",
             _ctx, plan, bool(reference),
             all([palm_data_a_left, palm_data_a_right, palm_data_b_left, palm_data_b_right]))

    target = build_target_input(
        face_a, name_a, birthdate_a,
        face_b, name_b, birthdate_b, ref_year,
        palm_data_a_left=palm_data_a_left,
        palm_data_a_right=palm_data_a_right,
        palm_data_b_left=palm_data_b_left,
        palm_data_b_right=palm_data_b_right,
    )
    examples_subdir = examples_dir / EXAMPLES_SUBDIR
    has_palm = all([palm_data_a_left, palm_data_a_right,
                    palm_data_b_left, palm_data_b_right])

    # ── Референс + ладони: перегенерируем только palmistry_heart ──
    if reference and has_palm:
        log.info("%scouple_report: режим reference+palm (точечная генерация palmistry_heart)", _ctx)
        blocks = _load_reference_blocks(reference)
        with open(examples_subdir / "reference_blocks.json", encoding="utf-8") as f:
            ref_ex = json.load(f)
        palm_block = _generate_palmistry_heart_block(
            target, ref_ex.get("palmistry_heart", {}), model=model,
            telegram_id=telegram_id,
        )
        blocks["palmistry_heart"] = palm_block["palmistry_heart"]
        errors = validate_blocks(blocks, has_palm=True)
        if errors:
            log.warning("%sПредупреждения валидации (reference + palm): %s", _ctx, errors)
        if _out_blocks is not None:
            _out_blocks.append(blocks)
        log.info("%scouple_report: завершён (reference+palm)", _ctx)
        return render_template(templates_dir, TEMPLATE_NAME, target, blocks, plan=plan)

    # ── Референс без ладоней: только рендеринг ──
    if reference:
        log.info("%scouple_report: режим reference-only (рендеринг без LLM)", _ctx)
        blocks = _load_reference_blocks(reference)
        errors = validate_blocks(blocks, has_palm=has_palm)
        if errors:
            log.warning("%sПредупреждения валидации (reference): %s", _ctx, errors)
        log.info("%scouple_report: завершён (reference-only)", _ctx)
        return render_template(templates_dir, TEMPLATE_NAME, target, blocks, plan=plan)

    log.info("%scouple_report: режим full LLM", _ctx)
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

    # Без ладоней — блок palmistry_heart остаётся null (шаблон скрывает секцию)

    if _out_blocks is not None:
        _out_blocks.append(blocks)

    log.info("%scouple_report: завершён (full LLM)", _ctx)
    return render_template(templates_dir, TEMPLATE_NAME, target, blocks, plan=plan)