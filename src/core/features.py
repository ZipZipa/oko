"""
Перевод метрик в текстовые описания черт.
LLM не должна сама решать "глаза глубокие" или "нос прямой" —
это даём детерминированно.
"""


def describe_face_shape(face_w_to_h: float, jaw_angle: float, cheekbone_ratio: float, jaw_width: float) -> str:
    if face_w_to_h > 0.85:
        return "круглое с широкими скулами"
    if face_w_to_h < 0.70:
        return "вытянутое, удлинённое"
    if jaw_angle < 120:
        return "квадратное с выраженной челюстью"
    if cheekbone_ratio > jaw_width * 1.05:
        return "сердцевидное, скулы шире челюсти"
    return "овальное, сбалансированное"


def describe_eyes(width_to_face: float, height_to_width: float, tilt_avg: float) -> dict:
    if height_to_width < 0.34:
        size = "глубокие, узковатые"
    elif height_to_width > 0.42:
        size = "крупные, открытые"
    else:
        size = "среднего размера"

    if tilt_avg > 132:
        shape = "с приподнятым внешним углом"
    elif tilt_avg < 128:
        shape = "с опущенным внешним углом"
    else:
        shape = "горизонтально посаженные"

    return {"size": size, "shape": shape, "summary": f"{size}, {shape}"}


def describe_nose(width_to_face: float, length_ratio: float, w_to_l: float) -> str:
    if width_to_face < 0.22:
        width = "узкий"
    elif width_to_face > 0.28:
        width = "широкий"
    else:
        width = "средней ширины"

    length = "длинный" if length_ratio > 0.27 else "короткий" if length_ratio < 0.22 else "пропорциональный"
    return f"{width}, {length}, прямой"


def describe_lips(width_to_face: float, fullness: float, upper_lower: float) -> str:
    if fullness < 0.20:
        thickness = "тонкие, плотно сжатые"
    elif fullness > 0.32:
        thickness = "полные, выразительные"
    else:
        thickness = "среднего объёма"

    if upper_lower < 0.55:
        balance = "с тонкой верхней губой"
    elif upper_lower > 0.75:
        balance = "с акцентом на верхней губе"
    else:
        balance = "сбалансированные"

    return f"{thickness}, {balance}"


def describe_brows(arch_avg: float, asym: float) -> str:
    if arch_avg < 0.10:
        shape = "прямые, без выраженной арки"
    elif arch_avg > 0.13:
        shape = "с выраженной аркой"
    else:
        shape = "со средней аркой"

    if asym > 0.020:
        shape += ", заметно асимметричные"
    return shape


def describe_jaw(angle_avg: float, width: float) -> dict:
    if angle_avg < 120:
        line = "выраженная, угловатая"
    elif angle_avg < 130:
        line = "средне очерченная"
    else:
        line = "мягкая, округлая"

    width_desc = "широкая" if width > 0.85 else "узкая" if width < 0.70 else "средней ширины"
    return {"line": line, "width": width_desc, "summary": f"{line}, {width_desc}"}


def describe_forehead(height_ratio: float) -> str:
    if height_ratio > 0.40:
        return "высокий"
    if height_ratio < 0.30:
        return "низкий"
    return "средней высоты, пропорциональный"


def describe_all_features(face_data: dict) -> dict:
    p = face_data.get("proportions")
    if not p or "details" not in p:
        return {
            "face_shape": "",
            "eyes": {}, "nose": {}, "lips": {},
            "brows": {}, "jaw": {}, "forehead": {},
        }
    d = p["details"]

    eyes = d["eyes"]
    nose = d["nose"]
    lips = d["lips"]
    brows = d["brows"]
    jaw = d["jaw"]

    eye_h_w_avg = (eyes["left_eye_height_to_width"] + eyes["right_eye_height_to_width"]) / 2
    eye_tilt_avg = (eyes["left_eye_tilt"] + eyes["right_eye_tilt"]) / 2
    jaw_angle_avg = (jaw["jaw_angle_left"] + jaw["jaw_angle_right"]) / 2
    brow_arch_avg = (brows["left_brow_arch_height"] + brows["right_brow_arch_height"]) / 2

    return {
        "face_shape": describe_face_shape(
            p["face_width_to_height"], jaw_angle_avg,
            d["cheekbones"]["cheekbone_width_to_face_width"],
            jaw["jaw_width_to_face_width"]
        ),
        "eyes": describe_eyes(
            (eyes["left_eye_width_to_face"] + eyes["right_eye_width_to_face"]) / 2,
            eye_h_w_avg, eye_tilt_avg
        ),
        "nose": describe_nose(
            nose["nose_width_to_face_width"],
            nose["nose_length_to_face_height"],
            nose["nose_width_to_length"]
        ),
        "lips": describe_lips(
            lips["mouth_width_to_face_width"],
            lips["lip_fullness"],
            lips["upper_lip_to_lower_ratio"]
        ),
        "brows": describe_brows(brow_arch_avg, d["asymmetry"]["brow_asymmetry"]),
        "jaw": describe_jaw(jaw_angle_avg, jaw["jaw_width_to_face_width"]),
        "forehead": describe_forehead(d["forehead"]["forehead_height_to_face"]),
    }
