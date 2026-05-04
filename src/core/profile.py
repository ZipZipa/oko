"""
Сборка профиля одного человека — общая логика для всех типов отчётов.
self_report использует её напрямую,
couple_report зовёт её дважды (для A и B),
money_report использует + добавляет money_dynamics.
"""
from datetime import datetime

from .numerology import full_numerology_profile
from .matrix import calculate_matrix
from .features import describe_all_features
from .scoring import calculate_all_scores
from .archetypes import (
    get_life_path_info, get_arcana_info, get_personal_year_meaning
)


def build_person_profile(face_data: dict, name: str, birthdate: str,
                         ref_year: int = None,
                         include_scores: bool = True,
                         include_matrix_raw: bool = False) -> dict:
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
    df = face_data["deepface"]

    profile = {
        "user": {
            "name": name,
            "birthdate": birthdate,
            "age": numerology["age"],
            "gender": df["gender"],
            "ethnicity_dominant": df.get("race", ""),
        },
        "features": features,
        "numerology": numerology_enriched,
        "matrix": matrix_enriched,
    }

    if include_scores:
        profile["scores"] = calculate_all_scores(face_data)

    if include_matrix_raw:
        profile["matrix_raw"] = matrix_raw

    return profile
