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


def score_skin_placeholder(emotion_neutral: float) -> float:
    """Без модели кожи возвращаем нейтральный скор 6.0.
    В будущем можно подключить skin-model или Haut.AI."""
    return 6.0


def score_grooming_placeholder() -> float:
    """Без модели волос/бороды возвращаем нейтральный скор 5.5."""
    return 5.5


def calculate_overall_score(scores: dict) -> float:
    """Взвешенное среднее основных метрик."""
    weights = {
        "symmetry": 0.20,
        "proportions": 0.20,
        "bone_structure": 0.20,
        "eyes": 0.20,
        "skin": 0.10,
        "grooming": 0.10,
    }
    total = sum(scores[k] * weights[k] for k in weights if k in scores)
    return round(total, 1)


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
        "skin": score_skin_placeholder(face_data["deepface"]["emotions"]["neutral"]),
        "grooming": score_grooming_placeholder(),
    }
    scores["overall"] = calculate_overall_score(scores)
    return scores
