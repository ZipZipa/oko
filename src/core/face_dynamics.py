"""
Контраст и совпадение черт двух лиц.
Используется для блока совместимости и хиромантии (по чертам).
"""


def _is_hard_jaw(jaw_summary: str) -> bool:
    return any(w in jaw_summary for w in ["выраженная", "угловатая"])


def _is_open_eyes(eyes_summary: str) -> bool:
    return any(w in eyes_summary for w in ["крупные", "открытые"])


def _is_full_lips(lips_text: str) -> bool:
    return "полные" in lips_text or "выразительные" in lips_text


def face_contrast(features_a: dict, features_b: dict) -> dict:
    """
    Сравнивает базовые типажи лиц.
    Возвращает структурированную динамику.
    """
    same_shape = features_a["face_shape"] == features_b["face_shape"]

    a_hard = _is_hard_jaw(features_a["jaw"]["summary"])
    b_hard = _is_hard_jaw(features_b["jaw"]["summary"])

    if a_hard and b_hard:
        jaw_dynamic = {"label": "оба жёсткие", "desc": "Конкурентная пара — оба не любят уступать"}
    elif not a_hard and not b_hard:
        jaw_dynamic = {"label": "оба мягкие", "desc": "Спокойная пара без острых углов, риск пассивности"}
    else:
        jaw_dynamic = {"label": "контраст", "desc": "Жёсткое и мягкое — классическое притяжение через противоположности"}

    a_open = _is_open_eyes(features_a["eyes"]["summary"])
    b_open = _is_open_eyes(features_b["eyes"]["summary"])

    if a_open and b_open:
        eyes_dynamic = {"label": "оба открытые", "desc": "Лёгкость в общении, прямой контакт"}
    elif not a_open and not b_open:
        eyes_dynamic = {"label": "оба закрытые", "desc": "Глубина, но мало спонтанности"}
    else:
        eyes_dynamic = {"label": "разная открытость", "desc": "Один тянет другого наружу, второй — вглубь"}

    a_full = _is_full_lips(features_a["lips"])
    b_full = _is_full_lips(features_b["lips"])

    if a_full and b_full:
        lips_dynamic = {"label": "оба чувственные", "desc": "Высокая физическая совместимость"}
    elif not a_full and not b_full:
        lips_dynamic = {"label": "оба сдержанные", "desc": "Сдержанность в проявлении чувств"}
    else:
        lips_dynamic = {"label": "контраст", "desc": "Один открыт телесно, другой сдержан"}

    return {
        "same_face_shape": same_shape,
        "jaw_dynamic": jaw_dynamic,
        "eyes_dynamic": eyes_dynamic,
        "lips_dynamic": lips_dynamic,
    }


def matrix_overlap(matrix_a: dict, matrix_b: dict) -> dict:
    """Какие позиции матрицы совпадают."""
    overlaps = []
    for key in matrix_a:
        if matrix_a[key] == matrix_b[key]:
            overlaps.append({
                "position": key,
                "arcana_number": matrix_a[key],
            })

    return {
        "common_arcanas": overlaps,
        "common_count": len(overlaps),
    }
