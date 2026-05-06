"""
Психологические сигналы с ладони — «след характера» на руке.
Аналог face_signals.py, но для palm_data.
Извлекает интерпретируемые паттерны из пропорций, линий, кривизны, кожи.
"""
from typing import Optional


# ═══════════════════════════════════════════════════════════════
# Справочники
# ═══════════════════════════════════════════════════════════════

ELEMENT_TYPES = {
    "earth": {
        "name_ru": "Земля",
        "description": "Широкая квадратная ладонь, короткие пальцы — прагматик, стабильность, опора",
    },
    "air": {
        "name_ru": "Воздух",
        "description": "Прямоугольная ладонь, длинные пальцы — мыслитель, коммуникация, идеи",
    },
    "water": {
        "name_ru": "Вода",
        "description": "Узкая вытянутая ладонь, длинные пальцы — эмпат, интуиция, чувствительность",
    },
    "fire": {
        "name_ru": "Огонь",
        "description": "Широкая ладонь, короткие/средние пальцы — лидер, действие, страсть",
    },
}

FINGER_MEANINGS = {
    "thumb": {
        "name_ru": "большой",
        "theme": "воля и самостоятельность",
        "dominant": "Сильная воля, лидерские замашки, потребность контролировать",
    },
    "index": {
        "name_ru": "указательный",
        "theme": "амбиции и авторитет",
        "dominant": "Амбициозность, стремление к статусу, авторитетность",
    },
    "middle": {
        "name_ru": "средний",
        "theme": "ответственность и баланс",
        "dominant": "Чувство ответственности, системность, карьерный фокус",
    },
    "ring": {
        "name_ru": "безымянный",
        "theme": "творчество и самовыражение",
        "dominant": "Креативность, потребность в признании, эстетическое чутьё",
    },
    "pinky": {
        "name_ru": "мизинец",
        "theme": "коммуникация и хитрость",
        "dominant": "Коммуникабельность, деловая хватка, дипломатичность",
    },
}

RATIO_2D4D = {
    "high_feminine": {
        "threshold": 1.0,
        "label": "высокий (женский тип)",
        "interpretation": "Указательный ≥ безымянного — высокий пренатальный эстроген, "
                          "развиты эмпатия, вербальные способности, склонность к сотрудничеству",
    },
    "masculine": {
        "threshold": 0.0,  # всё что < 1.0
        "label": "низкий (мужской тип)",
        "interpretation": "Безымянный длиннее указательного — высокий пренатальный тестостерон, "
                          "развиты пространственное мышление, рискованность, конкуренция",
    },
}

CURVATURE_THRESHOLDS = {
    "straight": (0.0, 0.01, "прямой", "целеустремлённость, жёсткость позиции"),
    "slight": (0.01, 0.02, "слегка изогнут", "гибкость, адаптивность"),
    "curved": (0.02, 1.0, "заметно изогнут", "выраженная гибкость, творческий подход"),
}

LINE_MEANINGS = {
    "heart_line": {
        "name_ru": "Линия сердца",
        "theme": "эмоциональная сфера",
        "strong": "Глубокая эмоциональность, открытость в чувствах",
        "weak": "Сдержанность в эмоциях, рациональный подход к отношениям",
    },
    "head_line": {
        "name_ru": "Линия головы",
        "theme": "интеллект и мышление",
        "strong": "Ясный ум, аналитические способности, фокус на мысли",
        "weak": "Интуитивное мышление, меньше опоры на логику",
    },
    "life_line": {
        "name_ru": "Линия жизни",
        "theme": "жизненная энергия",
        "strong": "Высокий жизненный тонус, устойчивость, напор",
        "weak": "Энергия распределяется экономно, периоды восстановления",
    },
    "fate_line": {
        "name_ru": "Линия судьбы",
        "theme": "предназначение и карьера",
        "strong": "Ясное чувство цели, карьерная определённость",
        "weak": "Свобода от внешних рамок, путь формируется самостоятельно",
    },
}


# ═══════════════════════════════════════════════════════════════
# Основная функция
# ═══════════════════════════════════════════════════════════════

def extract_hand_signals(palm_data: dict,
                         face_data: dict = None) -> dict:
    """
    Извлечь психологические сигналы из данных ладони.

    Возвращает dict с 6 секциями:
      element_type, dominant_finger, ratio_2d4d, spread_and_curvature,
      line_patterns, skin_contrast
    """
    props = palm_data.get("proportions", {})
    lines = palm_data.get("lines", {})
    skin = palm_data.get("skin", {})

    result = {
        "element_type": _element_type(props),
        "dominant_finger": _dominant_finger(props),
        "ratio_2d4d": _ratio_2d4d(props),
        "spread_and_curvature": _spread_and_curvature(props),
        "line_patterns": _line_patterns(lines),
    }

    # Контраст кожи ладони vs лица — только если face_data передан
    if face_data:
        result["skin_contrast"] = _skin_contrast(skin, face_data)

    # Ключевой паттерн линий — итоговый инсайт
    result["key_line_pattern"] = _key_line_pattern(lines)

    return result


# ═══════════════════════════════════════════════════════════════
# Приватные функции
# ═══════════════════════════════════════════════════════════════

def _element_type(props: dict) -> dict:
    """Определение стихии руки по пропорциям."""
    w_to_h = props.get("palm_width_to_height", 0.8)
    ratios = props.get("finger_ratios", {})
    lengths = props.get("finger_lengths", {})

    # Средняя длина пальцев относительно ладони
    finger_sum = sum(lengths.get(f, 0) for f in ("index", "middle", "ring", "pinky"))
    n_fingers = sum(1 for f in ("index", "middle", "ring", "pinky") if lengths.get(f, 0) > 0)
    avg_finger = finger_sum / n_fingers if n_fingers > 0 else 0.9

    if w_to_h > 0.90 and avg_finger < 0.95:
        element = "earth"
    elif w_to_h <= 0.80 and avg_finger > 0.95:
        element = "water"
    elif w_to_h > 0.85 and avg_finger < 0.92:
        element = "fire"
    else:
        element = "air"

    info = ELEMENT_TYPES[element]
    return {
        "element": element,
        "name_ru": info["name_ru"],
        "ratio": w_to_h,
        "avg_finger_length": round(avg_finger, 3),
        "palm_shape": props.get("palm_shape", ""),
        "description": info["description"],
    }


def _dominant_finger(props: dict) -> dict:
    """Доминирующий палец и его значение."""
    dominant = props.get("dominant_finger", "")
    ratios = props.get("finger_ratios", {})
    lengths = props.get("finger_lengths", {})

    info = FINGER_MEANINGS.get(dominant, {})
    thumb_to_idx = ratios.get("thumb_to_index", 0)
    thumb_angle = props.get("finger_angles", {}).get("thumb_angle", None)

    result = {
        "finger": dominant,
        "name_ru": info.get("name_ru", dominant),
        "theme": info.get("theme", ""),
        "thumb_to_index": thumb_to_idx,
        "interpretation": info.get("dominant", ""),
    }
    if thumb_angle is not None:
        result["thumb_angle"] = thumb_angle
    return result


def _ratio_2d4d(props: dict) -> dict:
    """2D:4D ratio и интерпретация."""
    ratios = props.get("finger_ratios", {})
    val = ratios.get("index_to_ring_2D4D", 0)

    if val >= 1.0:
        info = RATIO_2D4D["high_feminine"]
    else:
        info = RATIO_2D4D["masculine"]

    return {
        "value": val,
        "label": info["label"],
        "interpretation": info["interpretation"],
    }


def _spread_and_curvature(props: dict) -> dict:
    """Растопыренность и кривизна пальцев."""
    spread = props.get("finger_spread", {})
    curv = props.get("finger_curvature", {})

    # Растопыренность — выделяем заметные пары
    spread_items = []
    spread_labels = {
        "index_middle": "указательный–средний",
        "middle_ring": "средний–безымянный",
        "ring_pinky": "безымянный–мизинец",
    }
    for key, label in spread_labels.items():
        val = spread.get(key, 0)
        interp = ""
        if key == "ring_pinky" and val > 0.8:
            interp = "Широкий зазор — независимость мышления, нежелание подчиняться правилам"
        elif key == "index_middle" and val > 0.6:
            interp = "Умеренный зазор — баланс амбиций и ответственности"
        elif key == "middle_ring" and val > 0.5:
            interp = "Связь ответственности и творчества"
        spread_items.append({"pair": label, "value": val, "interpretation": interp})

    avg_spread = spread.get("avg_spread_to_palm", 0)
    spread_summary = ""
    if avg_spread > 0.9:
        spread_summary = "Широкая разводка — независимость, свобода, открытость новому"
    elif avg_spread > 0.6:
        spread_summary = "Умеренная разводка — баланс свободы и дисциплины"
    else:
        spread_summary = "Плотная разводка — собранность, дисциплина, закрытость"

    # Кривизна пальцев — выделяем заметные
    curv_items = []
    for finger, val in curv.items():
        info = FINGER_MEANINGS.get(finger, {})
        for label, (lo, hi, curv_label, interp) in CURVATURE_THRESHOLDS.items():
            if lo <= val < hi:
                curv_items.append({
                    "finger": info.get("name_ru", finger),
                    "value": val,
                    "label": curv_label,
                    "interpretation": f"{info.get('theme', '')}: {interp}",
                })
                break

    return {
        "spread": spread_items,
        "avg_spread": avg_spread,
        "spread_summary": spread_summary,
        "curvature": curv_items,
    }


def _line_patterns(lines: dict) -> list[dict]:
    """Паттерны линий ладони с интерпретацией."""
    if not lines.get("detection_available"):
        return []

    result = []
    for key, info in LINE_MEANINGS.items():
        ln = lines.get(key, {})
        present = ln.get("present", False)
        depth = ln.get("depth", 0)
        length = ln.get("length", "absent")
        curvature = ln.get("curvature", 0)
        branching = ln.get("branching", False)

        if not present:
            result.append({
                "name": info["name_ru"],
                "present": False,
                "interpretation": f"{info['theme']}: линия не выражена — {info['weak']}",
            })
            continue

        # Сильная или слабая линия
        strength = "strong" if depth >= 0.8 else "weak"
        strength_interp = info[strength]

        details = f"длина={length}, глубина={depth}, кривизна={curvature}"
        if branching:
            details += ", ветвление"

        # Дополнительная интерпретация по параметрам
        extra = []
        if curvature > 0.15:
            extra.append("изогнута — гибкость в данной сфере")
        if branching:
            extra.append("ветвится — множество путей и выборов")
        if depth < 0.7:
            extra.append("поверхностна — сфера не в фокусе внимания")

        result.append({
            "name": info["name_ru"],
            "present": True,
            "depth": depth,
            "length": length,
            "curvature": curvature,
            "branching": branching,
            "strength": strength,
            "strength_label": "глубокая" if strength == "strong" else "слабая",
            "details": details,
            "interpretation": strength_interp,
            "nuances": extra,
        })

    return result


def _skin_contrast(skin: dict, face_data: dict = None) -> dict:
    """Контраст текстуры кожи: ладонь vs лицо."""
    palm_smooth = skin.get("texture", {}).get("smoothness", 0)

    face_smooth = 0
    if face_data:
        face_skin = face_data.get("skin", {})
        if not face_skin.get("_stub", True):
            face_smooth = face_skin.get("texture", {}).get("smoothness", 0)

    diff = round(palm_smooth - face_smooth, 3)

    if abs(diff) < 0.15:
        interp = "Текстура ладони и лица согласованы — человек живёт в согласии с собой"
    elif diff > 0:
        interp = "Ладонь глаже лица — внутренняя устойчивость при внешних нагрузках"
    else:
        interp = "Ладонь грубее лица — активная практическая деятельность, руки в работе"

    return {
        "palm_smoothness": palm_smooth,
        "face_smoothness": face_smooth,
        "contrast": diff,
        "interpretation": interp,
    }


def _key_line_pattern(lines: dict) -> dict:
    """Ключевой паттерн: какая линия выделяется на фоне остальных."""
    if not lines.get("detection_available"):
        return {"description": "Линии не детектированы", "interpretation": ""}

    line_depths = {}
    for key in ("heart_line", "head_line", "life_line", "fate_line"):
        ln = lines.get(key, {})
        if ln.get("present", False):
            line_depths[key] = ln.get("depth", 0)

    if not line_depths:
        return {"description": "Нет выраженных линий", "interpretation": ""}

    strongest_key = max(line_depths, key=line_depths.get)
    weakest_key = min(line_depths, key=line_depths.get)

    # Если одна линия заметно слабее остальных
    avg_depth = sum(line_depths.values()) / len(line_depths)
    weak_lines = [k for k, v in line_depths.items() if v < avg_depth * 0.75]

    if weak_lines:
        weak_names = [LINE_MEANINGS[k]["name_ru"] for k in weak_lines]
        strong_names = [LINE_MEANINGS[k]["name_ru"] for k in line_depths if k not in weak_lines]
        desc = f"{' ,'.join(weak_names)} слабее {' ,'.join(strong_names)}"
        interp_parts = []
        for k in weak_lines:
            info = LINE_MEANINGS[k]
            interp_parts.append(f"{info['name_ru']} ({info['theme']}): {info['weak'].lower()}")
        interp = "; ".join(interp_parts)
    else:
        desc = "Все линии примерно равной глубины"
        interp = "Сбалансированность сфер — эмоции, разум, энергия, предназначение в равновесии"

    return {
        "strongest": LINE_MEANINGS[strongest_key]["name_ru"],
        "weakest": LINE_MEANINGS[weakest_key]["name_ru"],
        "description": desc,
        "interpretation": interp,
    }