"""Сборка контекста для чата «Спросить ОКО».

Чат отвечает на основе того же материала, из которого собираются отчёты:
рассчитанный профиль человека (нумерология, матрица, черты лица, ладони)
плюс тексты уже сгенерированных блоков self / money / couple.

Сборка профиля — чистый Python (никаких сетевых вызовов и ML), но всё же
не бесплатная, поэтому результат кешируется по отпечатку данных пользователя.
"""
import hashlib
import json
import logging

from src.bot.config import CHAT_CONTEXT_MAX_CHARS
from src.bot.db import User

log = logging.getLogger(__name__)

_PLAN_LEVEL = {"demo": 0, "base": 1, "extended": 2, "full": 3}

_REPORT_TITLES = {
    "self":   "ПОРТРЕТ ЛИЧНОСТИ",
    "money":  "ДЕНЕЖНАЯ КАРТА",
    "couple": "СОВМЕСТИМОСТЬ ПАРЫ",
}

# telegram_id → (fingerprint, context_text)
_cache: dict[int, tuple[str, str]] = {}
_CACHE_MAX_ENTRIES = 500


def max_plan(user: User) -> str:
    """Максимальный купленный пакет среди всех отчётов ('demo' — ничего не куплено)."""
    plans = [user.purchased_plan, user.money_plan, user.couple_plan]
    best = "demo"
    for plan in plans:
        if plan and _PLAN_LEVEL.get(plan, 0) > _PLAN_LEVEL[best]:
            best = plan
    return best


def owned_reports(user: User) -> list[str]:
    """Типы отчётов, по которым у пользователя есть платный пакет."""
    owned = []
    for report_type, plan in (
        ("self", user.purchased_plan),
        ("money", user.money_plan),
        ("couple", user.couple_plan),
    ):
        if plan and plan != "demo":
            owned.append(report_type)
    return owned


def _fingerprint(user: User) -> str:
    parts = [
        user.name or "", str(user.birth_date or ""),
        user.face_json or "", user.palm_left_json or "", user.palm_right_json or "",
        user.blocks_json or "", user.money_blocks_json or "", user.couple_blocks_json or "",
        user.partner_name or "", str(user.partner_birth_date or ""),
        user.partner_face_json or "",
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def build_context(user: User) -> str:
    """Текстовый контекст пользователя для системного промпта чата."""
    fp = _fingerprint(user)
    cached = _cache.get(user.telegram_id)
    if cached and cached[0] == fp:
        return cached[1]

    context = _build_context_uncached(user)

    if len(_cache) >= _CACHE_MAX_ENTRIES:
        _cache.clear()
    _cache[user.telegram_id] = (fp, context)
    return context


def _build_context_uncached(user: User) -> str:
    sections: list[str] = []

    profile_text = _profile_section(user)
    if profile_text:
        sections.append(profile_text)

    # Бюджет на блоки отчётов — то, что осталось от общего потолка
    remaining = max(CHAT_CONTEXT_MAX_CHARS - len(profile_text), 2000)
    report_sections = _report_sections(user)
    if report_sections:
        per_report = remaining // len(report_sections)
        for title, body in report_sections:
            sections.append(f"=== {title} (из отчёта) ===\n{_truncate(body, per_report)}")

    if not sections:
        return "Данных пользователя пока нет."
    return "\n\n".join(sections)


def _profile_section(user: User) -> str:
    """Рассчитанный профиль: нумерология, матрица, черты лица, ладони."""
    if not (user.face_json and user.birth_date and user.name):
        return ""

    from src.core.profile import build_person_profile, prepare_for_llm

    try:
        face_data = json.loads(user.face_json)
        palm_left = json.loads(user.palm_left_json) if user.palm_left_json else None
        palm_right = json.loads(user.palm_right_json) if user.palm_right_json else None
        profile = build_person_profile(
            face_data=face_data,
            name=user.name,
            birthdate=user.birth_date.strftime("%d.%m.%Y"),
            palm_data_left=palm_left,
            palm_data_right=palm_right,
        )
    except Exception:
        log.error("build_context: не удалось собрать профиль tg=%s",
                  user.telegram_id, exc_info=True)
        return ""

    # photo_url — это base64 data URI, в текстовый контекст ему нельзя
    profile.get("user", {}).pop("photo_url", None)
    profile = prepare_for_llm(profile)

    text = json.dumps(profile, ensure_ascii=False, indent=1)
    return f"=== ПРОФИЛЬ (рассчитан алгоритмами, числа менять нельзя) ===\n{text}"


def _report_sections(user: User) -> list[tuple[str, str]]:
    """Блоки сгенерированных отчётов как (заголовок, текст)."""
    sources = [
        ("self",   user.blocks_json),
        ("money",  user.money_blocks_json),
        ("couple", user.couple_blocks_json),
    ]
    sections: list[tuple[str, str]] = []
    for report_type, raw in sources:
        if not raw:
            continue
        try:
            blocks = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("build_context: битый %s blocks_json tg=%s",
                        report_type, user.telegram_id)
            continue
        sections.append((
            _REPORT_TITLES[report_type],
            json.dumps(blocks, ensure_ascii=False, indent=1),
        ))
    return sections


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n… (фрагмент отчёта обрезан)"
