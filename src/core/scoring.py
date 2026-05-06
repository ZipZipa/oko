"""
Перевод сырых метрик MediaPipe/DeepFace в скоры 0-10.
Эмпирические пороги, дающие стабильные значения.
"""


def _clamp(value: float, lo: float = 0.0, hi: float = 10.0) -> float:
    return round(max(lo, min(hi, value)), 1)


def score_symmetry(face_asymmetry: float) -> float:
    """face_asymmetry обычно 0.005-0.05. Чем меньше — тем симметричнее."""
    if face_asymmetry < 0.008: return 9.0
    if face_asymmetry < 0.012: return 8.0
    if face_asymmetry < 0.016: return 7.0
    if face_asymmetry < 0.020: return 6.5
    if face_asymmetry < 0.025: return 6.0
    if face_asymmetry < 0.030: return 5.5
    if face_asymmetry < 0.040: return 5.0
    return 4.0


def score_proportions(face_w_to_h: float, forehead_ratio: float) -> float:
    """
    Идеал: face_w_to_h ~ 0.75, forehead_ratio ~ 0.35.
    Используем мягкую функцию убывания, чтобы не получать 0 при разумных отклонениях.
    """
    ideal_wh = 0.75
    ideal_forehead = 0.35

    wh_dev = abs(face_w_to_h - ideal_wh) / ideal_wh
    fh_dev = abs(forehead_ratio - ideal_forehead) / ideal_forehead

    # каждое отклонение даёт штраф до ~3 баллов
    wh_score = 9.0 - min(wh_dev * 8, 4)
    fh_score = 9.0 - min(fh_dev * 4, 4)

    return _clamp((wh_score + fh_score) / 2)


def score_bone_structure(jaw_angle_avg: float, cheekbone_ratio: float, jaw_width: float) -> float:
    """Структура лица: челюсть и скулы. Острее челюсть = выше скор."""
    # jaw_angle: 110° острая, 140° мягкая
    if jaw_angle_avg < 115: jaw_score = 9.0
    elif jaw_angle_avg < 120: jaw_score = 8.0
    elif jaw_angle_avg < 125: jaw_score = 7.0
    elif jaw_angle_avg < 130: jaw_score = 6.0
    elif jaw_angle_avg < 135: jaw_score = 5.5
    else: jaw_score = 5.0

    # выраженные скулы шире челюсти
    cheek_score = 7.0 if cheekbone_ratio > jaw_width else 6.0

    return _clamp((jaw_score + cheek_score) / 2)


def score_eyes(eye_height_to_width_avg: float, eye_asymmetry: float) -> float:
    """Глаза: открытость и симметрия."""
    # 0.30 узкие, 0.40 средние, 0.50 крупные
    if eye_height_to_width_avg < 0.30: openness = 5.5
    elif eye_height_to_width_avg < 0.36: openness = 6.5
    elif eye_height_to_width_avg < 0.42: openness = 7.5
    else: openness = 8.0

    asym_penalty = min(eye_asymmetry * 100, 1.5)
    return _clamp(openness - asym_penalty)


def calculate_overall_score(scores: dict) -> float:
    """Взвешенное среднее основных метрик."""
    weights = {
        "symmetry": 0.25,
        "proportions": 0.25,
        "bone_structure": 0.25,
        "eyes": 0.25,
    }
    total = sum(scores[k] * weights[k] for k in weights if k in scores)
    return round(total, 1)


def score_grooming(skin_data: dict, stylistic_markers: list | None = None) -> float:
    """Скор ухоженности на основе кожи и стилистических маркеров.

    Факторы:
    - roughness (ниже = лучше) → 0-4 балла
    - evenness по зонам (ниже = лучше) → 0-3 балла
    - stylistic_markers (серьга и т.д.) → 0-1.5 балла
    - smoothness → 0-1.5 балла
    """
    texture = skin_data.get("texture", {})
    roughness = texture.get("roughness", 0.5)
    smoothness = texture.get("smoothness", 0.5)

    # Roughness: 0.0-0.3 → 4.0, 0.3-0.5 → 3.0, 0.5-0.7 → 2.0, 0.7-0.9 → 1.0, >0.9 → 0.5
    if roughness < 0.3:
        rough_score = 4.0
    elif roughness < 0.5:
        rough_score = 3.0
    elif roughness < 0.7:
        rough_score = 2.0
    elif roughness < 0.9:
        rough_score = 1.0
    else:
        rough_score = 0.5

    # Evenness: среднее по зонам, ниже = ровнее
    evenness = skin_data.get("evenness", {})
    by_zone = evenness.get("by_zone", {})
    if by_zone:
        avg_evenness = sum(by_zone.values()) / len(by_zone)
        # avg_evenness 0.0-0.15 → 3.0, 0.15-0.25 → 2.0, 0.25-0.35 → 1.0, >0.35 → 0.5
        if avg_evenness < 0.15:
            even_score = 3.0
        elif avg_evenness < 0.25:
            even_score = 2.0
        elif avg_evenness < 0.35:
            even_score = 1.0
        else:
            even_score = 0.5
    else:
        even_score = 1.5  # нет данных — средний

    # Stylistic markers (серьга и т.д.) — признак заботы о внешности
    marker_score = 1.5 if stylistic_markers else 0.0

    # Smoothness
    if smoothness > 0.7:
        smooth_score = 1.5
    elif smoothness > 0.4:
        smooth_score = 1.0
    else:
        smooth_score = 0.5

    return _clamp(rough_score + even_score + marker_score + smooth_score)


def score_skin(skin_data: dict) -> float:
    """Скор качества кожи на основе текстуры и ровности.

    Факторы:
    - roughness (ниже = лучше) → 0-4 балла
    - smoothness (выше = лучше) → 0-3 балла
    - evenness среднее по зонам (ниже = лучше) → 0-3 балла
    """
    texture = skin_data.get("texture", {})
    roughness = texture.get("roughness", 0.5)
    smoothness = texture.get("smoothness", 0.5)

    # Roughness
    if roughness < 0.2:
        rough_score = 4.0
    elif roughness < 0.4:
        rough_score = 3.0
    elif roughness < 0.6:
        rough_score = 2.0
    elif roughness < 0.8:
        rough_score = 1.0
    else:
        rough_score = 0.5

    # Smoothness
    if smoothness > 0.8:
        smooth_score = 3.0
    elif smoothness > 0.5:
        smooth_score = 2.0
    elif smoothness > 0.3:
        smooth_score = 1.0
    else:
        smooth_score = 0.5

    # Evenness
    evenness = skin_data.get("evenness", {})
    by_zone = evenness.get("by_zone", {})
    if by_zone:
        avg_evenness = sum(by_zone.values()) / len(by_zone)
        if avg_evenness < 0.10:
            even_score = 3.0
        elif avg_evenness < 0.20:
            even_score = 2.0
        elif avg_evenness < 0.30:
            even_score = 1.0
        else:
            even_score = 0.5
    else:
        even_score = 1.5

    return _clamp(rough_score + smooth_score + even_score)


def calculate_all_scores(face_data: dict) -> dict:
    """Главная функция: на вход — твой JSON, на выход — все скоры."""
    proportions = face_data["proportions"]
    details = proportions["details"]

    eyes = details["eyes"]
    nose = details["nose"]
    jaw = details["jaw"]
    asym = details["asymmetry"]

    eye_avg_h_w = (eyes["left_eye_height_to_width"] + eyes["right_eye_height_to_width"]) / 2
    jaw_avg = (jaw["jaw_angle_left"] + jaw["jaw_angle_right"]) / 2

    scores = {
        "symmetry": score_symmetry(asym["face_asymmetry"]),
        "proportions": score_proportions(
            proportions["face_width_to_height"],
            proportions["forehead_to_face_ratio"]
        ),
        "bone_structure": score_bone_structure(
            jaw_avg,
            details["cheekbones"]["cheekbone_width_to_face_width"],
            jaw["jaw_width_to_face_width"]
        ),
        "eyes": score_eyes(eye_avg_h_w, asym["eye_asymmetry"]),
    }
    scores["overall"] = calculate_overall_score(scores)

    # Grooming & skin — из skin_data
    skin_data = face_data.get("skin", {})
    stylistic_markers = None
    # Попробуем получить stylistic_markers из face_signals, если они есть
    if "face_signals" in face_data:
        stylistic_markers = face_data["face_signals"].get("stylistic_markers")

    if skin_data and not skin_data.get("_stub", True):
        scores["grooming"] = score_grooming(skin_data, stylistic_markers)
        scores["skin"] = score_skin(skin_data)

    return scores
