"""
Сборка профиля одного человека — общая логика для всех типов отчётов.
self_report использует её напрямую,
couple_report зовёт её дважды (для A и B),
money_report использует + добавляет money_dynamics.
"""
import copy
from datetime import datetime

from .numerology import full_numerology_profile
from .matrix import calculate_matrix
from .features import describe_all_features
from .scoring import calculate_all_scores
from .face_signals import extract_face_signals
from .palm_signals import extract_hand_signals
from .archetypes import (
    get_life_path_info, get_arcana_info, get_personal_year_meaning
)


def build_person_profile(face_data: dict, name: str, birthdate: str,
                         ref_year: int = None,
                         include_scores: bool = True,
                         include_matrix_raw: bool = False,
                         palm_data_left: dict = None,
                         palm_data_right: dict = None) -> dict:
    """
    Профиль одного человека. Используется как кирпич всеми типами отчётов.

    include_scores: для парного отчёта внешность не нужна — отключаем
    include_matrix_raw: для пары нужны сырые числа матрицы для overlap
    """
    if ref_year is None:
        ref_year = datetime.now().year

    numerology = full_numerology_profile(birthdate, ref_year=ref_year)
    lp_info = get_life_path_info(numerology["life_path"])

    numerology_enriched = {
        "life_path": numerology["life_path"],
        "life_path_archetype": {
            "name": lp_info["name"],
            "short": lp_info["short"],
            "lesson": lp_info["lesson"],
        },
        "day": numerology["day"],
        "personal_year": {
            "year": ref_year,
            "number": numerology["personal_year"]["number"],
            "meaning": get_personal_year_meaning(numerology["personal_year"]["number"]),
        },
        "pinnacles": numerology["pinnacles"],
        "formula": numerology["formula"],
    }

    matrix_raw = calculate_matrix(birthdate)
    matrix_enriched = {
        key: {**get_arcana_info(num)} for key, num in matrix_raw.items()
    }

    features = describe_all_features(face_data)
    df = face_data.get("deepface", {})
    face_signals = extract_face_signals(face_data)
    has_both_palms = palm_data_left is not None and palm_data_right is not None
    hand_signals = extract_hand_signals(palm_data_left, palm_data_right, face_data) if has_both_palms else None

    user_dict = {
        "name": name,
        "birthdate": birthdate,
        "age": numerology["age"],
        "gender": df.get("gender", ""),
        "ethnicity_dominant": df.get("race", ""),
        # face_shape канонический — из features (детерминированный алгоритм)
        "face_shape": features["face_shape"],
    }
    # photo_url может быть передан внутри face_data (например, из CLI как base64 data URI)
    if face_data.get("photo_url"):
        user_dict["photo_url"] = face_data["photo_url"]

    profile = {
        "user": user_dict,
        "features": features,
        "face_signals": face_signals,
        "hand_signals": hand_signals,
        "numerology": numerology_enriched,
        "matrix": matrix_enriched,
    }

    if include_scores:
        profile["scores"] = calculate_all_scores(face_data)

    # Grooming-сигналы — берём skin_contrast из правой руки (ближе к реальности)
    grooming_hand = hand_signals.get("right") if hand_signals else None
    profile["grooming_signals"] = _build_grooming_signals(
        face_data, face_signals, grooming_hand,
        profile.get("scores", {}),
    )

    if include_matrix_raw:
        profile["matrix_raw"] = matrix_raw

    return profile


def _build_grooming_signals(face_data: dict, face_signals: dict,
                             hand_signals: dict | None,
                             scores: dict) -> dict:
    """
    Сборка grooming_signals — данные для блока grooming_and_style.

    Источники:
      - face_data.skin → roughness, evenness
      - face_signals.skin_signals → зоны кожи
      - face_signals.stylistic_markers → аксессуары
      - hand_signals.skin_contrast → контраст ухода ладонь/лицо (если есть)
      - scores.grooming, scores.skin → итоговые скоры
    """
    skin_raw = face_data.get("skin", {})
    # _stub=True или отсутствие _stub → заглушка, не используем
    if not skin_raw or skin_raw.get("_stub", True):
        skin_raw = {}

    roughness = skin_raw.get("texture", {}).get("roughness", None)
    evenness = skin_raw.get("evenness", {}).get("by_zone", {})

    # Состояние кожи — только текстовая метка, без числа
    if roughness is not None and roughness > 0.8:
        skin_condition = "Кожа с выраженной шероховатостью — нужен уход"
    elif roughness is not None and roughness > 0.5:
        skin_condition = "Умеренная шероховатость кожи — средний уровень ухода"
    elif roughness is not None:
        skin_condition = "Кожа гладкая — хороший уровень ухода"
    else:
        skin_condition = "Данные о текстуре кожи недоступны"

    # Зоны напряжения — только названия зон, без числовых значений
    tension_zone_names = []
    if evenness:
        for zone, val in evenness.items():
            if isinstance(val, (int, float)) and val > 0.25:
                tension_zone_names.append(zone)
            elif isinstance(val, dict):
                for sub_zone, sub_val in val.items():
                    if isinstance(sub_val, (int, float)) and sub_val > 0.25:
                        tension_zone_names.append(f"{zone}.{sub_zone}")

    # Аксессуары — только label и interpretation, без числового value
    stylistic = face_signals.get("stylistic_markers", [])
    accessories = [{"label": m["label"], "interpretation": m["interpretation"]} for m in stylistic]

    # Кожа из face_signals — только summary и tension_zones (без числовых zone_signals)
    skin_signals_raw = face_signals.get("skin_signals", {})
    skin_signals = {
        "summary": skin_signals_raw.get("summary", ""),
        "tension_zones": skin_signals_raw.get("tension_zones", []),
    } if skin_signals_raw else {}

    # Контраст ладонь/лицо — только интерпретация
    skin_contrast = None
    if hand_signals and "skin_contrast" in hand_signals:
        skin_contrast = hand_signals["skin_contrast"].get("interpretation", "")

    # Скоры — текстовые метки вместо чисел
    grooming_score_raw = scores.get("grooming", None)
    skin_score_raw = scores.get("skin", None)
    grooming_level = _score_label(grooming_score_raw)
    skin_level = _score_label(skin_score_raw)

    return {
        "skin_condition": skin_condition,
        "tension_zones": tension_zone_names,
        "skin_signals": skin_signals,
        "accessories": accessories,
        "skin_contrast": skin_contrast,
        "grooming_level": grooming_level,
        "skin_level": skin_level,
    }


_MATRIX_KEY_RU = {
    "personality":    "Личность",
    "realization":    "Реализация",
    "destiny":        "Предназначение",
    "karma_rod":      "Карма рода",
    "family_program": "Родовая программа",
    "challenge":      "Испытание",
    "money":          "Деньги",
    "love":           "Любовь",
    "health":         "Здоровье",
    "mission":        "Миссия",
    "spiritual_path": "Духовный путь",
    "creativity":     "Творчество",
    "comfort":        "Комфорт",
}

_PALM_KEY_RU = {
    "ratio_2d4d": "соотношение_указательного_к_безымянному",
}


def prepare_for_llm(profile: dict) -> dict:
    """Переименовывает технические английские ключи перед отправкой в LLM."""
    profile = copy.deepcopy(profile)

    if "matrix" in profile:
        profile["matrix"] = {
            _MATRIX_KEY_RU.get(k, k): v for k, v in profile["matrix"].items()
        }

    for side in ("left", "right"):
        palm = (profile.get("hand_signals") or {}).get(side)
        if palm:
            palm.update({_PALM_KEY_RU[k]: palm.pop(k) for k in list(palm) if k in _PALM_KEY_RU})

    return profile


def _score_label(score: float | None) -> str:
    if score is None:
        return "нет данных"
    if score >= 8.0:
        return "высокий"
    if score >= 6.0:
        return "выше среднего"
    if score >= 4.0:
        return "средний"
    if score >= 2.0:
        return "ниже среднего"
    return "низкий"
