"""
Текстовые описания метрик ладони для подачи в LLM.
Аналог face_features.py, но для palm_analyzer.
"""
from typing import Dict, Any


def describe_palm(palm_data: dict) -> str:
    """Развёрнутое текстовое описание результатов анализа ладони."""
    parts: list[str] = []

    proportions = palm_data.get("proportions", {})
    lines = palm_data.get("lines", {})
    skin = palm_data.get("skin", {})

    # --- Форма и пропорции ---
    shape = proportions.get("palm_shape", "не определена")
    w_h = proportions.get("palm_width_to_height", 0)
    handed = proportions.get("handedness", "?")
    dominant = proportions.get("dominant_finger", "?")

    parts.append(f"Форма ладони: {shape}")
    parts.append(f"Отношение ширины к высоте: {w_h}")
    parts.append(f"Рука: {handed}")
    parts.append(f"Доминирующий палец: {dominant}")

    # --- Соотношения пальцев ---
    ratios = proportions.get("finger_ratios", {})
    r_2d4d = ratios.get("index_to_ring_2D4D", 0)
    r_idx_mid = ratios.get("index_to_middle", 0)
    r_ring_mid = ratios.get("ring_to_middle", 0)
    r_pnk_ring = ratios.get("pinky_to_ring", 0)
    r_thm_idx = ratios.get("thumb_to_index", 0)

    parts.append(f"2D:4D (указательный/безымянный): {r_2d4d}")
    if r_2d4d >= 1.0:
        parts.append("  → указательный ≥ безымянного (типично для женщин / низкий пренатальный тестостерон)")
    else:
        parts.append("  → безымянный длиннее указательного (типично для мужчин / высокий пренатальный тестостерон)")

    parts.append(f"Указательный/средний: {r_idx_mid}")
    parts.append(f"Безымянный/средний: {r_ring_mid}")
    parts.append(f"Мизинец/безымянный: {r_pnk_ring}")
    if r_pnk_ring < 0.75:
        parts.append("  → короткий мизинец")
    parts.append(f"Большой/указательный: {r_thm_idx}")

    # --- Длины пальцев ---
    lengths = proportions.get("finger_lengths", {})
    parts.append("Длины пальцев (нормализованные к высоте ладони):")
    for name, val in lengths.items():
        _name_ru = {"thumb": "большой", "index": "указательный", "middle": "средний", "ring": "безымянный", "pinky": "мизинец"}.get(name, name)
        parts.append(f"  {_name_ru}: {val}")

    # --- Углы ---
    angles = proportions.get("finger_angles", {})
    parts.append(f"Угол большого пальца: {angles.get('thumb_angle', 0)}°")
    if angles.get("thumb_angle", 0) > 50:
        parts.append("  → большой палец отставлен (гибкость, открытость)")
    else:
        parts.append("  → большой палец прижат (сдержанность)")
    parts.append(f"Угол PIP указательного: {angles.get('index_pip', 0)}°")
    parts.append(f"Угол PIP среднего: {angles.get('middle_pip', 0)}°")
    parts.append(f"Угол PIP безымянного: {angles.get('ring_pip', 0)}°")
    parts.append(f"Угол PIP мизинца: {angles.get('pinky_pip', 0)}°")

    # --- Кривизна ---
    curv = proportions.get("finger_curvature", {})
    parts.append("Кривизна пальцев:")
    for name, val in curv.items():
        _name_ru = {"thumb": "большой", "index": "указательный", "middle": "средний", "ring": "безымянный", "pinky": "мизинец"}.get(name, name)
        parts.append(f"  {_name_ru}: {val}")

    # --- Разводка ---
    spread = proportions.get("finger_spread", {})
    avg_spr = spread.get("avg_spread_to_palm", 0)
    parts.append(f"Средняя разводка пальцев/ширина ладони: {avg_spr}")
    if avg_spr > 1.0:
        parts.append("  → широкая разводка (независимость, свобода)")
    else:
        parts.append("  → узкая разводка (собранность, дисциплина)")

    # --- Линии ладони ---
    if lines.get("detection_available"):
        for line_key, line_name_ru in [
            ("heart_line", "Линия сердца"),
            ("head_line", "Линия головы"),
            ("life_line", "Линия жизни"),
            ("fate_line", "Линия судьбы"),
        ]:
            ln = lines.get(line_key, {})
            present = ln.get("present", False)
            if present:
                length = ln.get("length", "?")
                depth = ln.get("depth", 0)
                curv_l = ln.get("curvature", 0)
                branch = ln.get("branching", False)
                desc = f"{line_name_ru}: длина={length}, глубина={depth}, кривизна={curv_l}"
                if branch:
                    desc += ", ветвление"
                parts.append(desc)
            else:
                parts.append(f"{line_name_ru}: не обнаружена")
    else:
        parts.append("Детекция линий ладони недоступна")

    # --- Кожа ---
    if not skin.get("_stub", True):
        tone = skin.get("tone", {})
        parts.append(f"Тон кожи: hue={tone.get('hue', 0)}, saturation={tone.get('saturation', 0)}, brightness={tone.get('brightness', 0)}")
        parts.append(f"Подтон: {tone.get('undertone', '?')}")
        evenness = skin.get("evenness", {}).get("overall", 0)
        parts.append(f"Ровность кожи: {evenness}")
        texture = skin.get("texture", {})
        parts.append(f"Гладкость: {texture.get('smoothness', 0)}, шероховатость: {texture.get('roughness', 0)}")
    else:
        parts.append("Анализ кожи ладони недоступен")

    return "\n".join(parts)


def palm_features_compact(palm_data: dict) -> Dict[str, Any]:
    """Компактное представление для контекста LLM."""
    proportions = palm_data.get("proportions", {})
    lines = palm_data.get("lines", {})
    skin = palm_data.get("skin", {})

    ratios = proportions.get("finger_ratios", {})
    lengths = proportions.get("finger_lengths", {})
    angles = proportions.get("finger_angles", {})
    curv = proportions.get("finger_curvature", {})
    spread = proportions.get("finger_spread", {})

    compact_lines = {}
    if lines.get("detection_available"):
        for k in ("heart_line", "head_line", "life_line", "fate_line"):
            ln = lines.get(k, {})
            compact_lines[k] = {
                "present": ln.get("present", False),
                "length": ln.get("length", "absent"),
                "depth": ln.get("depth", 0),
                "curvature": ln.get("curvature", 0),
                "branching": ln.get("branching", False),
            }

    compact_skin = {}
    if not skin.get("_stub", True):
        tone = skin.get("tone", {})
        compact_skin = {
            "hue": tone.get("hue", 0),
            "saturation": tone.get("saturation", 0),
            "brightness": tone.get("brightness", 0),
            "undertone": tone.get("undertone", "?"),
            "evenness": skin.get("evenness", {}).get("overall", 0),
            "smoothness": skin.get("texture", {}).get("smoothness", 0),
            "roughness": skin.get("texture", {}).get("roughness", 0),
        }

    return {
        "palm_shape": proportions.get("palm_shape", ""),
        "palm_width_to_height": proportions.get("palm_width_to_height", 0),
        "handedness": proportions.get("handedness", ""),
        "dominant_finger": proportions.get("dominant_finger", ""),
        "finger_ratios": ratios,
        "finger_lengths": lengths,
        "finger_angles": angles,
        "finger_curvature": curv,
        "finger_spread": spread,
        "lines": compact_lines,
        "skin": compact_skin,
    }