"""
Анализ лица: DeepFace (возраст, пол, раса, эмоции) + MediaPipe FaceLandmarker (пропорции, поза, кожа, blendshapes).
На выходе — JSON, совместимый с sample_face_artem.json.
"""
import os

# DeepFace использует Keras 2 API через tf-keras.
# Без этого флага TensorFlow 2.16+ подхватывает Keras 3, и модели DeepFace падают:
# "A KerasTensor cannot be used as input to a TensorFlow function"
os.environ["TF_USE_LEGACY_KERAS"] = "1"
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
os.environ["CUDA_VISIBLE_DEVICES"] = ""          # GPU отключен — предотвращает краш на VDS без CUDA
os.environ["GLOG_minloglevel"] = "2"             # подавляет abseil/CUDA-логи

import math
import threading
import urllib.request
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import mediapipe as mp
from deepface import DeepFace

# MediaPipe Tasks API
BaseOptions = mp.tasks.BaseOptions
FaceLandmarker = mp.tasks.vision.FaceLandmarker
FaceLandmarkerOptions = mp.tasks.vision.FaceLandmarkerOptions
FaceLandmarkerResult = mp.tasks.vision.FaceLandmarkerResult
VisionRunningMode = mp.tasks.vision.RunningMode

# Кэш landmarker-объекта (создаётся один раз, переиспользуется)
_face_landmarker: FaceLandmarker | None = None
_face_landmarker_lock = threading.Lock()


def _get_face_landmarker() -> FaceLandmarker:
    """Возвращает синглтон FaceLandmarker (потокобезопасно, delegate=CPU)."""
    global _face_landmarker
    if _face_landmarker is None:
        with _face_landmarker_lock:
            if _face_landmarker is None:
                model_path = _ensure_model()
                options = FaceLandmarkerOptions(
                    base_options=BaseOptions(
                        model_asset_path=model_path,
                        delegate=BaseOptions.Delegate.CPU,
                    ),
                    running_mode=VisionRunningMode.IMAGE,
                    num_faces=1,
                    min_face_detection_confidence=0.5,
                    min_face_presence_confidence=0.5,
                    min_tracking_confidence=0.5,
                    output_face_blendshapes=True,
                    output_facial_transformation_matrixes=True,
                )
                _face_landmarker = FaceLandmarker.create_from_options(options)
    return _face_landmarker


# Путь к модели
_MODEL_DIR = Path(__file__).resolve().parent.parent / "models"
_MODEL_URL = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task"


# ---------------------------------------------------------------------------
# Индексы ключевых точек FaceMesh (478 точек, та же сетка)
# ---------------------------------------------------------------------------
FACE_OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288,
             397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136,
             172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109]

LEFT_EYE = [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246]
RIGHT_EYE = [362, 382, 381, 380, 374, 373, 390, 249, 263, 466, 388, 387, 386, 385, 384, 398]

LEFT_BROW = [70, 63, 105, 66, 107, 55, 65, 52, 53, 46]
RIGHT_BROW = [300, 293, 334, 296, 336, 285, 295, 282, 283, 276]


# ---------------------------------------------------------------------------
# Загрузка модели
# ---------------------------------------------------------------------------
def _ensure_model() -> str:
    """Скачивает модель face_landmarker.task если её нет. Возвращает путь."""
    _MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model_path = _MODEL_DIR / "face_landmarker.task"
    if not model_path.exists():
        urllib.request.urlretrieve(_MODEL_URL, str(model_path))
    return str(model_path)


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------
def _dist(a: dict, b: dict) -> float:
    """Евклидово расстояние между двумя landmarks."""
    return math.sqrt((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2)


def _midpoint(a: dict, b: dict) -> dict:
    return {"x": (a["x"] + b["x"]) / 2, "y": (a["y"] + b["y"]) / 2, "z": (a.get("z", 0) + b.get("z", 0)) / 2}


def _angle_three_points(p1: dict, p2: dict, p3: dict) -> float:
    """Угол в точке p2 между p1-p2-p3 (в градусах)."""
    v1 = {"x": p1["x"] - p2["x"], "y": p1["y"] - p2["y"]}
    v2 = {"x": p3["x"] - p2["x"], "y": p3["y"] - p2["y"]}
    dot = v1["x"] * v2["x"] + v1["y"] * v2["y"]
    mag1 = math.sqrt(v1["x"] ** 2 + v1["y"] ** 2)
    mag2 = math.sqrt(v2["x"] ** 2 + v2["y"] ** 2)
    if mag1 * mag2 == 0:
        return 180.0
    cos_angle = max(-1.0, min(1.0, dot / (mag1 * mag2)))
    return math.degrees(math.acos(cos_angle))


def _get_landmark(landmarks_list, idx: int) -> dict:
    """Получить landmark по индексу из NormalizedLandmark."""
    lm = landmarks_list[idx]
    return {"x": lm.x, "y": lm.y, "z": lm.z}


def _compute_face_width(landmarks) -> float:
    left = _get_landmark(landmarks, 234)
    right = _get_landmark(landmarks, 454)
    return _dist(left, right)


def _compute_face_height(landmarks) -> float:
    top = _get_landmark(landmarks, 10)
    bottom = _get_landmark(landmarks, 152)
    return _dist(top, bottom)


# ---------------------------------------------------------------------------
# DeepFace анализ
# ---------------------------------------------------------------------------
def _analyze_deepface(image_path: str, detector: str = "retinaface") -> dict:
    """Запуск DeepFace: возраст, пол, раса, эмоции."""
    try:
        result = DeepFace.analyze(
            img_path=image_path,
            actions=["age", "gender", "race", "emotion"],
            detector_backend=detector,
            enforce_detection=True,
            align=True,
            silent=True,
        )
        if isinstance(result, list):
            result = result[0]

        age = result.get("age", 0)
        gender = result.get("dominant_gender", "Unknown")
        gender_probs = result.get("gender", {})
        race = result.get("dominant_race", "Unknown")
        race_probs = result.get("race", {})
        emotion = result.get("dominant_emotion", "neutral")
        emotion_probs = result.get("emotion", {})

        return {
            "age": int(age) if isinstance(age, (int, float)) else 0,
            "gender": gender,
            "gender_probabilities": {k: float(v) for k, v in gender_probs.items()} if isinstance(gender_probs, dict) else {},
            "race": race,
            "race_probabilities": {k: float(v) for k, v in race_probs.items()} if isinstance(race_probs, dict) else {},
            "dominant_emotion": emotion,
            "emotions": {k: float(v) for k, v in emotion_probs.items()} if isinstance(emotion_probs, dict) else {},
        }
    except ValueError as e:
        raise ValueError(f"DeepFace: лицо не обнаружено — {e}")
    except Exception as e:
        if detector != "opencv":
            return _analyze_deepface(image_path, detector="opencv")
        raise RuntimeError(f"DeepFace: ошибка анализа — {e}")


# ---------------------------------------------------------------------------
# MediaPipe FaceLandmarker анализ (Tasks API)
# ---------------------------------------------------------------------------
def _analyze_mediapipe(image_path: str) -> dict:
    """
    Запуск MediaPipe FaceLandmarker (Tasks API): пропорции, поза головы, blendshapes, кожа.
    """
    image = cv2.imread(image_path)
    if image is None:
        raise ValueError(f"Не удалось загрузить изображение: {image_path}")

    h, w, _ = image.shape
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    # Используем кэшированный landmarker (синглтон, delegate=CPU)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    landmarker = _get_face_landmarker()
    result = landmarker.detect(mp_image)

    if not result.face_landmarks:
        raise ValueError("MediaPipe: лицо не обнаружено")

    landmarks = result.face_landmarks[0]

    # ===================================================================
    # ОСНОВНЫЕ РАЗМЕРЫ
    # ===================================================================
    face_w = _compute_face_width(landmarks)
    face_h = _compute_face_height(landmarks)
    face_w_to_h = round(face_w / face_h, 3) if face_h > 0 else 0.0

    # ===================================================================
    # ГЛАЗА
    # ===================================================================
    left_eye_left = _get_landmark(landmarks, 33)
    left_eye_right = _get_landmark(landmarks, 133)
    left_eye_top = _get_landmark(landmarks, 159)
    left_eye_bottom = _get_landmark(landmarks, 145)

    right_eye_left = _get_landmark(landmarks, 362)
    right_eye_right = _get_landmark(landmarks, 263)
    right_eye_top = _get_landmark(landmarks, 386)
    right_eye_bottom = _get_landmark(landmarks, 374)

    left_eye_width = _dist(left_eye_left, left_eye_right)
    left_eye_height = _dist(left_eye_top, left_eye_bottom)
    right_eye_width = _dist(right_eye_left, right_eye_right)
    right_eye_height = _dist(right_eye_top, right_eye_bottom)

    left_eye_width_to_face = round(left_eye_width / face_w, 3) if face_w > 0 else 0.0
    right_eye_width_to_face = round(right_eye_width / face_w, 3) if face_w > 0 else 0.0
    left_eye_height_to_width = round(left_eye_height / left_eye_width, 3) if left_eye_width > 0 else 0.0
    right_eye_height_to_width = round(right_eye_height / right_eye_width, 3) if right_eye_width > 0 else 0.0

    left_eye_tilt = math.degrees(math.atan2(
        left_eye_right["y"] - left_eye_left["y"],
        left_eye_right["x"] - left_eye_left["x"],
    ))
    right_eye_tilt = math.degrees(math.atan2(
        right_eye_right["y"] - right_eye_left["y"],
        right_eye_right["x"] - right_eye_left["x"],
    ))
    left_eye_tilt = round(abs(left_eye_tilt), 1)
    right_eye_tilt = round(abs(right_eye_tilt), 1)

    left_eye_inner = _get_landmark(landmarks, 133)
    right_eye_inner = _get_landmark(landmarks, 362)
    eye_distance = _dist(left_eye_inner, right_eye_inner)
    eye_spacing_to_face = round(eye_distance / face_w, 3) if face_w > 0 else 0.0

    eye_asymmetry = round(abs(left_eye_height_to_width - right_eye_height_to_width), 4)

    # ===================================================================
    # НОС
    # ===================================================================
    nose_left = _get_landmark(landmarks, 48)
    nose_right = _get_landmark(landmarks, 278)
    nose_bridge_top = _get_landmark(landmarks, 168)
    nose_tip = _get_landmark(landmarks, 1)
    nose_bottom = _get_landmark(landmarks, 2)

    nose_width = _dist(nose_left, nose_right)
    nose_length = _dist(nose_bridge_top, nose_tip)
    nose_width_to_face_width = round(nose_width / face_w, 3) if face_w > 0 else 0.0
    nose_length_to_face_height = round(nose_length / face_h, 3) if face_h > 0 else 0.0
    nose_width_to_length = round(nose_width / nose_length, 3) if nose_length > 0 else 0.0

    # ===================================================================
    # ГУБЫ / РОТ
    # ===================================================================
    mouth_left = _get_landmark(landmarks, 61)
    mouth_right = _get_landmark(landmarks, 291)
    upper_lip_top = _get_landmark(landmarks, 0)
    lower_lip_bottom = _get_landmark(landmarks, 17)
    upper_lip_center = _get_landmark(landmarks, 13)
    lower_lip_center = _get_landmark(landmarks, 14)

    mouth_width = _dist(mouth_left, mouth_right)
    mouth_height = _dist(upper_lip_center, lower_lip_center)
    lip_height_total = _dist(upper_lip_top, lower_lip_bottom)

    mouth_width_to_face_width = round(mouth_width / face_w, 3) if face_w > 0 else 0.0
    mouth_height_to_width = round(mouth_height / mouth_width, 3) if mouth_width > 0 else 0.0
    lip_fullness = round(lip_height_total / mouth_width, 3) if mouth_width > 0 else 0.0

    upper_lip_h = _dist(upper_lip_top, upper_lip_center)
    lower_lip_h = _dist(lower_lip_center, lower_lip_bottom)
    upper_lip_to_lower = round(upper_lip_h / lower_lip_h, 3) if lower_lip_h > 0 else 0.0

    # ===================================================================
    # БРОВИ
    # ===================================================================
    left_brow_inner = _get_landmark(landmarks, 55)
    left_brow_outer = _get_landmark(landmarks, 46)
    left_brow_arch = _get_landmark(landmarks, 105)

    right_brow_inner = _get_landmark(landmarks, 285)
    right_brow_outer = _get_landmark(landmarks, 276)
    right_brow_arch = _get_landmark(landmarks, 334)

    left_brow_length = _dist(left_brow_inner, left_brow_outer)
    right_brow_length = _dist(right_brow_inner, right_brow_outer)

    left_brow_length_to_face = round(left_brow_length / face_w, 3) if face_w > 0 else 0.0
    right_brow_length_to_face = round(right_brow_length / face_w, 3) if face_w > 0 else 0.0

    left_brow_arch_height = round(_dist(left_brow_arch, left_eye_top) / face_h, 4) if face_h > 0 else 0.0
    right_brow_arch_height = round(_dist(right_brow_arch, right_eye_top) / face_h, 4) if face_h > 0 else 0.0

    brow_asymmetry = round(abs(left_brow_arch_height - right_brow_arch_height), 4)

    # ===================================================================
    # ЧЕЛЮСТЬ
    # ===================================================================
    jaw_left_point = _get_landmark(landmarks, 172)
    jaw_right_point = _get_landmark(landmarks, 397)
    chin_point = _get_landmark(landmarks, 152)
    jaw_upper_left = _get_landmark(landmarks, 234)
    jaw_upper_right = _get_landmark(landmarks, 454)

    jaw_angle_left = _angle_three_points(jaw_upper_left, jaw_left_point, chin_point)
    jaw_angle_right = _angle_three_points(jaw_upper_right, jaw_right_point, chin_point)

    jaw_width = _dist(jaw_left_point, jaw_right_point)
    jaw_width_to_face_width = round(jaw_width / face_w, 3) if face_w > 0 else 0.0

    # ===================================================================
    # ЛОБ
    # ===================================================================
    forehead_top = _get_landmark(landmarks, 10)
    forehead_bottom = _get_landmark(landmarks, 151)
    forehead_height = _dist(forehead_top, forehead_bottom)
    forehead_height_to_face = round(forehead_height / face_h, 3) if face_h > 0 else 0.0

    # ===================================================================
    # СКУЛЫ
    # ===================================================================
    left_cheekbone = _get_landmark(landmarks, 116)
    right_cheekbone = _get_landmark(landmarks, 345)
    cheekbone_width = _dist(left_cheekbone, right_cheekbone)
    cheekbone_width_to_face_width = round(cheekbone_width / face_w, 3) if face_w > 0 else 0.0

    # ===================================================================
    # ФОРМА ЛИЦА
    # ===================================================================
    face_shape = _determine_face_shape(face_w_to_h, jaw_angle_left, jaw_angle_right,
                                        cheekbone_width_to_face_width, jaw_width_to_face_width)

    # ===================================================================
    # АСИММЕТРИЯ ЛИЦА
    # ===================================================================
    nose_bridge = _get_landmark(landmarks, 168)
    face_asymmetry = _compute_face_asymmetry(landmarks, nose_bridge)

    # ===================================================================
    # HEAD POSE (из матрицы трансформации)
    # ===================================================================
    head_pose = _extract_head_pose(result)

    # ===================================================================
    # BLENDSHAPES (реальные из модели!)
    # ===================================================================
    blendshapes = _extract_blendshapes(result)

    # ===================================================================
    # КОЖА
    # ===================================================================
    skin = _analyze_skin(image, landmarks, w, h)

    # ===================================================================
    # СБОРКА РЕЗУЛЬТАТА
    # ===================================================================
    proportions = {
        "face_width_to_height": face_w_to_h,
        "eye_distance_to_face_width": eye_spacing_to_face,
        "nose_to_chin_ratio": round(_dist(nose_tip, chin_point) / face_h, 3) if face_h > 0 else 0.0,
        "forehead_to_face_ratio": round(forehead_height / face_h, 3) if face_h > 0 else 0.0,
        "mouth_width_to_face_width": mouth_width_to_face_width,
        "brow_width_to_eye_distance": round(left_brow_length / eye_distance, 3) if eye_distance > 0 else 0.0,
        "face_shape": face_shape,
        "blendshapes": blendshapes,
        "head_pose": head_pose,
        "details": {
            "eyes": {
                "left_eye_width_to_face": left_eye_width_to_face,
                "right_eye_width_to_face": right_eye_width_to_face,
                "left_eye_height_to_width": left_eye_height_to_width,
                "right_eye_height_to_width": right_eye_height_to_width,
                "left_eye_tilt": left_eye_tilt,
                "right_eye_tilt": right_eye_tilt,
                "eye_spacing_to_face_width": eye_spacing_to_face,
                "eye_asymmetry": eye_asymmetry,
            },
            "nose": {
                "nose_width_to_face_width": nose_width_to_face_width,
                "nose_length_to_face_height": nose_length_to_face_height,
                "nose_width_to_length": nose_width_to_length,
            },
            "lips": {
                "mouth_width_to_face_width": mouth_width_to_face_width,
                "mouth_height_to_width": mouth_height_to_width,
                "lip_fullness": lip_fullness,
                "upper_lip_to_lower_ratio": upper_lip_to_lower,
            },
            "brows": {
                "left_brow_length_to_face_width": left_brow_length_to_face,
                "right_brow_length_to_face_width": right_brow_length_to_face,
                "left_brow_arch_height": left_brow_arch_height,
                "right_brow_arch_height": right_brow_arch_height,
                "brow_asymmetry": brow_asymmetry,
            },
            "jaw": {
                "jaw_angle_left": round(jaw_angle_left, 1),
                "jaw_angle_right": round(jaw_angle_right, 1),
                "jaw_width_to_face_width": jaw_width_to_face_width,
            },
            "forehead": {
                "forehead_height_to_face": forehead_height_to_face,
            },
            "cheekbones": {
                "cheekbone_width_to_face_width": cheekbone_width_to_face_width,
            },
            "asymmetry": {
                "face_asymmetry": face_asymmetry,
                "eye_asymmetry": eye_asymmetry,
                "brow_asymmetry": brow_asymmetry,
            },
        },
    }

    return {
        "proportions": proportions,
        "skin": skin,
    }


# ---------------------------------------------------------------------------
# Определение формы лица
# ---------------------------------------------------------------------------
def _determine_face_shape(w_to_h: float, jaw_angle_l: float, jaw_angle_r: float,
                          cheekbone_ratio: float, jaw_width: float) -> str:
    jaw_avg = (jaw_angle_l + jaw_angle_r) / 2
    if w_to_h > 0.85:
        return "круглое"
    if w_to_h < 0.70:
        return "вытянутая"
    if jaw_avg < 120:
        return "квадратное"
    if cheekbone_ratio > jaw_width * 1.05:
        return "сердцевидное"
    return "овальное"


# ---------------------------------------------------------------------------
# Асимметрия лица
# ---------------------------------------------------------------------------
def _compute_face_asymmetry(landmarks, nose_bridge: dict) -> float:
    pairs = [
        (234, 454), (33, 263), (133, 362), (61, 291), (55, 285), (46, 276),
    ]
    deviations = []
    for left_idx, right_idx in pairs:
        left = _get_landmark(landmarks, left_idx)
        right = _get_landmark(landmarks, right_idx)
        right_mirrored_x = 2 * nose_bridge["x"] - right["x"]
        dev = math.sqrt((left["x"] - right_mirrored_x) ** 2 + (left["y"] - right["y"]) ** 2)
        deviations.append(dev)
    return round(sum(deviations) / len(deviations), 4) if deviations else 0.0


# ---------------------------------------------------------------------------
# Head pose из матрицы трансформации (Tasks API)
# ---------------------------------------------------------------------------
def _extract_head_pose(result: FaceLandmarkerResult) -> dict:
    """
    Извлечение yaw, pitch, roll из матрицы трансформации лица.
    Tasks API возвращает 4x4 матрицу — извлекаем углы Эйлера.
    """
    if not result.facial_transformation_matrixes:
        return {"yaw": 0.0, "pitch": 0.0, "roll": 0.0}

    matrix = np.array(result.facial_transformation_matrixes[0]).reshape(4, 4)
    rmat = matrix[:3, :3]

    # Углы Эйлера (ZXY convention — стандарт для head pose)
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, -rmat[2, 0]))))
    yaw = math.degrees(math.atan2(rmat[2, 1], rmat[2, 2]))
    roll = math.degrees(math.atan2(rmat[1, 0], rmat[0, 0]))

    return {
        "yaw": round(yaw, 2),
        "pitch": round(pitch, 2),
        "roll": round(roll, 2),
    }


# ---------------------------------------------------------------------------
# Реальные blendshapes из модели (Tasks API)
# ---------------------------------------------------------------------------
# Маппинг имён blendshapes из модели → наши ключи
_BLENDSHAPE_MAP = {
    "_neutral": "_neutral",
    "browDownLeft": "browDownLeft",
    "browDownRight": "browDownRight",
    "browInnerUp": "browInnerUp",
    "browOuterUpLeft": "browOuterUpLeft",
    "browOuterUpRight": "browOuterUpRight",
    "cheekPuff": "cheekPuff",
    "cheekSquintLeft": "cheekSquintLeft",
    "cheekSquintRight": "cheekSquintRight",
    "eyeBlinkLeft": "eyeBlinkLeft",
    "eyeBlinkRight": "eyeBlinkRight",
    "eyeLookDownLeft": "eyeLookDownLeft",
    "eyeLookDownRight": "eyeLookDownRight",
    "eyeLookInLeft": "eyeLookInLeft",
    "eyeLookInRight": "eyeLookInRight",
    "eyeLookOutLeft": "eyeLookOutLeft",
    "eyeLookOutRight": "eyeLookOutRight",
    "eyeLookUpLeft": "eyeLookUpLeft",
    "eyeLookUpRight": "eyeLookUpRight",
    "eyeSquintLeft": "eyeSquintLeft",
    "eyeSquintRight": "eyeSquintRight",
    "eyeWideLeft": "eyeWideLeft",
    "eyeWideRight": "eyeWideRight",
    "jawForward": "jawForward",
    "jawLeft": "jawLeft",
    "jawOpen": "jawOpen",
    "jawRight": "jawRight",
    "mouthClose": "mouthClose",
    "mouthDimpleLeft": "mouthDimpleLeft",
    "mouthDimpleRight": "mouthDimpleRight",
    "mouthFrownLeft": "mouthFrownLeft",
    "mouthFrownRight": "mouthFrownRight",
    "mouthFunnel": "mouthFunnel",
    "mouthLeft": "mouthLeft",
    "mouthLowerDownLeft": "mouthLowerDownLeft",
    "mouthLowerDownRight": "mouthLowerDownRight",
    "mouthPressLeft": "mouthPressLeft",
    "mouthPressRight": "mouthPressRight",
    "mouthPucker": "mouthPucker",
    "mouthRight": "mouthRight",
    "mouthRollLower": "mouthRollLower",
    "mouthRollUpper": "mouthRollUpper",
    "mouthShrugLower": "mouthShrugLower",
    "mouthShrugUpper": "mouthShrugUpper",
    "mouthSmileLeft": "mouthSmileLeft",
    "mouthSmileRight": "mouthSmileRight",
    "mouthStretchLeft": "mouthStretchLeft",
    "mouthStretchRight": "mouthStretchRight",
    "mouthUpperUpLeft": "mouthUpperUpLeft",
    "mouthUpperUpRight": "mouthUpperUpRight",
    "noseSneerLeft": "noseSneerLeft",
    "noseSneerRight": "noseSneerRight",
}

# Все ключи, которые должны быть в выходе (для совместимости)
_ALL_BLENDSHAPE_KEYS = [
    "_neutral", "browDownLeft", "browDownRight", "browInnerUp",
    "browOuterUpLeft", "browOuterUpRight", "cheekPuff",
    "cheekSquintLeft", "cheekSquintRight", "eyeBlinkLeft",
    "eyeBlinkRight", "eyeLookDownLeft", "eyeLookDownRight",
    "eyeLookInLeft", "eyeLookInRight", "eyeLookOutLeft",
    "eyeLookOutRight", "eyeLookUpLeft", "eyeLookUpRight",
    "eyeSquintLeft", "eyeSquintRight", "eyeWideLeft", "eyeWideRight",
    "jawForward", "jawLeft", "jawOpen", "jawRight", "mouthClose",
    "mouthDimpleLeft", "mouthDimpleRight", "mouthFrownLeft",
    "mouthFrownRight", "mouthFunnel", "mouthLeft",
    "mouthLowerDownLeft", "mouthLowerDownRight", "mouthPressLeft",
    "mouthPressRight", "mouthPucker", "mouthRight",
    "mouthRollLower", "mouthRollUpper", "mouthShrugLower",
    "mouthShrugUpper", "mouthSmileLeft", "mouthSmileRight",
    "mouthStretchLeft", "mouthStretchRight", "mouthUpperUpLeft",
    "mouthUpperUpRight", "noseSneerLeft", "noseSneerRight",
]


def _extract_blendshapes(result: FaceLandmarkerResult) -> dict:
    """
    Извлечение реальных blendshapes из модели FaceLandmarker.
    Возвращает dict с 52 ключами-значениями (0.0–1.0).
    """
    # Инициализируем все нулями
    blendshapes = {key: 0.0 for key in _ALL_BLENDSHAPE_KEYS}

    if not result.face_blendshapes:
        return blendshapes

    # face_blendshapes — список Classifications (по одному на лицо)
    for category in result.face_blendshapes[0]:
        name = category.category_name
        score = round(category.score, 4)
        if name in _BLENDSHAPE_MAP:
            blendshapes[_BLENDSHAPE_MAP[name]] = score

    return blendshapes


# ---------------------------------------------------------------------------
# Анализ кожи
# ---------------------------------------------------------------------------
def _analyze_skin(image: np.ndarray, landmarks, w: int, h: int) -> dict:
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

    zones = {
        "forehead": [_get_landmark(landmarks, i) for i in [10, 109, 67, 103, 54, 21, 162]],
        "nose": [_get_landmark(landmarks, i) for i in [168, 6, 197, 195, 5, 4, 1, 2, 98, 327, 48, 278]],
        "left_cheek": [_get_landmark(landmarks, i) for i in [116, 117, 118, 119, 120, 121, 128, 147, 213, 192, 122, 50]],
        "right_cheek": [_get_landmark(landmarks, i) for i in [345, 346, 347, 348, 349, 350, 357, 376, 433, 416, 351, 280]],
        "chin": [_get_landmark(landmarks, i) for i in [152, 148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109]],
    }

    face_zone = [_get_landmark(landmarks, idx) for idx in FACE_OVAL]

    mask = _create_zone_mask(face_zone, w, h)
    if mask.sum() == 0:
        return _skin_stub()

    skin_pixels_hsv = hsv[mask > 0]
    skin_pixels_rgb = rgb[mask > 0]

    mean_h = np.mean(skin_pixels_hsv[:, 0])
    mean_s = np.mean(skin_pixels_hsv[:, 1])
    mean_v = np.mean(skin_pixels_hsv[:, 2])

    hue = round(mean_h * 2, 1)
    saturation = round(mean_s / 255, 3)
    brightness = round(mean_v / 255, 3)

    undertone = _determine_undertone(skin_pixels_rgb)

    evenness_by_zone = {}
    for zone_name, zone_points in zones.items():
        zone_mask = _create_zone_mask(zone_points, w, h)
        if zone_mask.sum() > 0:
            zone_pixels_hsv = hsv[zone_mask > 0]
            brightness_std = np.std(zone_pixels_hsv[:, 2]) / 255
            evenness = round(max(0, 1 - brightness_std * 3), 3)
            evenness_by_zone[zone_name] = evenness
        else:
            evenness_by_zone[zone_name] = 0.0

    overall_evenness = round(np.mean(list(evenness_by_zone.values())), 3)

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    grad_x = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
    gradient_magnitude = np.sqrt(grad_x ** 2 + grad_y ** 2)

    if mask.sum() > 0:
        skin_gradient = gradient_magnitude[mask > 0]
        mean_grad = np.mean(skin_gradient)
        roughness = round(min(1.0, mean_grad / 80), 3)
        smoothness = round(1.0 - roughness, 3)
    else:
        roughness = 0.5
        smoothness = 0.5

    zones_area = _compute_zones_area(landmarks, w, h)

    return {
        "tone": {
            "hue": hue,
            "saturation": saturation,
            "brightness": brightness,
            "undertone": undertone,
        },
        "evenness": {
            "overall": overall_evenness,
            "by_zone": evenness_by_zone,
        },
        "texture": {
            "smoothness": smoothness,
            "roughness": roughness,
        },
        "zones_area": zones_area,
        "segmentation_available": True,
        "_stub": False,
    }


def _create_zone_mask(points: list, w: int, h: int) -> np.ndarray:
    mask = np.zeros((h, w), dtype=np.uint8)
    if len(points) < 3:
        return mask
    pts = np.array([[int(p["x"] * w), int(p["y"] * h)] for p in points], dtype=np.int32)
    cv2.fillConvexPoly(mask, pts, 255)
    return mask


def _determine_undertone(skin_pixels_rgb: np.ndarray) -> str:
    if len(skin_pixels_rgb) == 0:
        return "нейтральный"
    r = np.mean(skin_pixels_rgb[:, 0])
    g = np.mean(skin_pixels_rgb[:, 1])
    b = np.mean(skin_pixels_rgb[:, 2])
    if r > b + 20 and g > b + 10:
        return "тёплый"
    elif b > r - 10:
        return "холодный"
    else:
        return "нейтральный"


def _compute_zones_area(landmarks, w: int, h: int) -> dict:
    face_points = [_get_landmark(landmarks, i) for i in FACE_OVAL]
    face_mask = _create_zone_mask(face_points, w, h)
    face_area = max(1, face_mask.sum())

    zone_defs = {
        "skin": FACE_OVAL,
        "nose": [168, 6, 197, 195, 5, 4, 1, 2, 98, 327, 48, 278],
        "left_eye": LEFT_EYE,
        "right_eye": RIGHT_EYE,
        "right_brow": RIGHT_BROW,
        "left_ear": [234, 93, 132, 58, 172],
        "upper_lip": [61, 185, 40, 39, 37, 0, 267, 269, 270, 409, 291],
        "lower_lip": [291, 375, 321, 405, 314, 17, 84, 181, 91, 146, 61],
        "mouth_interior": [78, 95, 88, 178, 87, 14, 317, 402, 318, 324, 308, 415, 310, 311, 312, 13, 82, 81, 80, 191],
    }

    zones_area = {}
    for name, indices in zone_defs.items():
        points = [_get_landmark(landmarks, i) for i in indices]
        zone_mask = _create_zone_mask(points, w, h)
        zones_area[name] = round(zone_mask.sum() / face_area, 3)

    zones_area["eye_glass"] = 0.01
    zones_area["ear_ring"] = 0.01

    return zones_area


def _skin_stub() -> dict:
    return {
        "tone": {"hue": 0.0, "saturation": 0.0, "brightness": 0.0, "undertone": "нейтральный"},
        "evenness": {"overall": 0.0, "by_zone": {}},
        "texture": {"smoothness": 0.0, "roughness": 0.0},
        "zones_area": {},
        "segmentation_available": False,
        "_stub": True,
    }


# ---------------------------------------------------------------------------
# Публичный API
# ---------------------------------------------------------------------------
def analyze_face(image_path: str, deepface_detector: str = "retinaface") -> dict:
    """
    Полный анализ лица из фото.

    Args:
        image_path: Путь к изображению
        deepface_detector: Детектор для DeepFace ('retinaface', 'opencv', 'ssd', 'mtcnn', 'skip')

    Returns:
        dict с ключами: deepface, proportions, skin
    """
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Изображение не найдено: {image_path}")

    deepface_result = _analyze_deepface(image_path, detector=deepface_detector)
    mediapipe_result = _analyze_mediapipe(image_path)

    return {
        "deepface": deepface_result,
        "proportions": mediapipe_result["proportions"],
        "skin": mediapipe_result["skin"],
    }