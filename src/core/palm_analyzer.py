"""
Анализ ладони: MediaPipe HandLandmarker (21 точка → пропорции пальцев/ладони) +
OpenCV + Gabor/Ridge (детекция линий ладони) + анализ кожи.
На выходе — JSON, совместимый по структуре с face_analyzer.
"""
import logging
import os

# GPU отключен — предотвращает краш на VDS без CUDA (идентично face_analyzer)
os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
os.environ["GLOG_minloglevel"] = "2"

import math
import threading
import time
import urllib.request
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import mediapipe as mp

log = logging.getLogger(__name__)

# MediaPipe Tasks API
BaseOptions = mp.tasks.BaseOptions
HandLandmarker = mp.tasks.vision.HandLandmarker
HandLandmarkerOptions = mp.tasks.vision.HandLandmarkerOptions
HandLandmarkerResult = mp.tasks.vision.HandLandmarkerResult
VisionRunningMode = mp.tasks.vision.RunningMode

# Кэш landmarker-объекта (создаётся один раз, переиспользуется)
_hand_landmarker: HandLandmarker | None = None
_hand_landmarker_lock = threading.Lock()


def _get_hand_landmarker() -> HandLandmarker:
    """Возвращает синглтон HandLandmarker (потокобезопасно, delegate=CPU)."""
    global _hand_landmarker
    if _hand_landmarker is None:
        with _hand_landmarker_lock:
            if _hand_landmarker is None:
                model_path = _ensure_model()
                options = HandLandmarkerOptions(
                    base_options=BaseOptions(
                        model_asset_path=model_path,
                        delegate=BaseOptions.Delegate.CPU,
                    ),
                    running_mode=VisionRunningMode.IMAGE,
                    num_hands=1,
                    min_hand_detection_confidence=0.5,
                    min_hand_presence_confidence=0.5,
                    min_tracking_confidence=0.5,
                )
                _hand_landmarker = HandLandmarker.create_from_options(options)
    return _hand_landmarker


# Путь к модели
_MODEL_DIR = Path(__file__).resolve().parent.parent / "models"
_HAND_MODEL_URL = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task"


# ---------------------------------------------------------------------------
# Индексы ключевых точек HandLandmarker (21 точка)
# ---------------------------------------------------------------------------
# 0  — WRIST
# 1  — THUMB_CMC
# 2  — THUMB_MCP
# 3  — THUMB_IP
# 4  — THUMB_TIP
# 5  — INDEX_FINGER_MCP
# 6  — INDEX_FINGER_PIP
# 7  — INDEX_FINGER_DIP
# 8  — INDEX_FINGER_TIP
# 9  — MIDDLE_FINGER_MCP
# 10 — MIDDLE_FINGER_PIP
# 11 — MIDDLE_FINGER_DIP
# 12 — MIDDLE_FINGER_TIP
# 13 — RING_FINGER_MCP
# 14 — RING_FINGER_PIP
# 15 — RING_FINGER_DIP
# 16 — RING_FINGER_TIP
# 17 — PINKY_MCP
# 18 — PINKY_PIP
# 19 — PINKY_DIP
# 20 — PINKY_TIP

WRIST = 0
THUMB_CMC, THUMB_MCP, THUMB_IP, THUMB_TIP = 1, 2, 3, 4
INDEX_MCP, INDEX_PIP, INDEX_DIP, INDEX_TIP = 5, 6, 7, 8
MIDDLE_MCP, MIDDLE_PIP, MIDDLE_DIP, MIDDLE_TIP = 9, 10, 11, 12
RING_MCP, RING_PIP, RING_DIP, RING_TIP = 13, 14, 15, 16
PINKY_MCP, PINKY_PIP, PINKY_DIP, PINKY_TIP = 17, 18, 19, 20

# Группы точек по пальцам
THUMB_POINTS = [THUMB_CMC, THUMB_MCP, THUMB_IP, THUMB_TIP]
INDEX_POINTS = [INDEX_MCP, INDEX_PIP, INDEX_DIP, INDEX_TIP]
MIDDLE_POINTS = [MIDDLE_MCP, MIDDLE_PIP, MIDDLE_DIP, MIDDLE_TIP]
RING_POINTS = [RING_MCP, RING_PIP, RING_DIP, RING_TIP]
PINKY_POINTS = [PINKY_MCP, PINKY_PIP, PINKY_DIP, PINKY_TIP]

# Точки основания пальцев (для ширины ладони)
FINGER_BASES = [INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP]


# ---------------------------------------------------------------------------
# Загрузка модели
# ---------------------------------------------------------------------------
def _ensure_model() -> str:
    """Скачивает модель hand_landmarker.task если её нет. Возвращает путь."""
    _MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model_path = _MODEL_DIR / "hand_landmarker.task"
    if not model_path.exists():
        urllib.request.urlretrieve(_HAND_MODEL_URL, str(model_path))
    return str(model_path)


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------
def _dist(a: dict, b: dict) -> float:
    """Евклидово расстояние между двумя landmarks."""
    return math.sqrt((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2)


def _dist3d(a: dict, b: dict) -> float:
    """Евклидово 3D расстояние."""
    return math.sqrt(
        (a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2 + (a.get("z", 0) - b.get("z", 0)) ** 2
    )


def _midpoint(a: dict, b: dict) -> dict:
    return {
        "x": (a["x"] + b["x"]) / 2,
        "y": (a["y"] + b["y"]) / 2,
        "z": (a.get("z", 0) + b.get("z", 0)) / 2,
    }


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


def _angle_between_vectors(v1: dict, v2: dict) -> float:
    """Угол между двумя векторами (в градусах)."""
    dot = v1["x"] * v2["x"] + v1["y"] * v2["y"]
    mag1 = math.sqrt(v1["x"] ** 2 + v1["y"] ** 2)
    mag2 = math.sqrt(v2["x"] ** 2 + v2["y"] ** 2)
    if mag1 * mag2 == 0:
        return 0.0
    cos_angle = max(-1.0, min(1.0, dot / (mag1 * mag2)))
    return math.degrees(math.acos(cos_angle))


def _get_landmark(landmarks_list, idx: int) -> dict:
    """Получить landmark по индексу из NormalizedLandmark."""
    lm = landmarks_list[idx]
    return {"x": lm.x, "y": lm.y, "z": lm.z}


def _finger_length(landmarks, tip: int, dip: int, pip: int, mcp: int) -> float:
    """Длина пальца от MCP до TIP через PIP и DIP."""
    p_mcp = _get_landmark(landmarks, mcp)
    p_pip = _get_landmark(landmarks, pip)
    p_dip = _get_landmark(landmarks, dip)
    p_tip = _get_landmark(landmarks, tip)
    return _dist(p_mcp, p_pip) + _dist(p_pip, p_dip) + _dist(p_dip, p_tip)


def _finger_curvature(landmarks, tip: int, dip: int, pip: int, mcp: int) -> float:
    """Кривизна пальца: отклонение TIP от прямой MCP→TIP (нормализованное)."""
    p_mcp = _get_landmark(landmarks, mcp)
    p_pip = _get_landmark(landmarks, pip)
    p_dip = _get_landmark(landmarks, dip)
    p_tip = _get_landmark(landmarks, tip)

    # Прямая от MCP к воображаемому кончику (продолжение MCP→DIP)
    finger_len = _dist(p_mcp, p_tip)
    if finger_len == 0:
        return 0.0

    # Отклонение PIP от прямой MCP→DIP
    deviation = _point_line_distance(p_pip, p_mcp, p_dip)
    return round(deviation / finger_len, 4)


def _point_line_distance(point: dict, line_a: dict, line_b: dict) -> float:
    """Расстояние от точки до прямой, заданной двумя точками."""
    dx = line_b["x"] - line_a["x"]
    dy = line_b["y"] - line_a["y"]
    denom = math.sqrt(dx * dx + dy * dy)
    if denom == 0:
        return 0.0
    return abs(dy * point["x"] - dx * point["y"] + line_b["x"] * line_a["y"] - line_b["y"] * line_a["x"]) / denom


# ---------------------------------------------------------------------------
# MediaPipe HandLandmarker анализ
# ---------------------------------------------------------------------------
def _analyze_hand_landmarks(image_path: str) -> dict:
    """
    Запуск MediaPipe HandLandmarker: пропорции пальцев, форма ладони, углы.
    """
    image = cv2.imread(image_path)
    if image is None:
        raise ValueError(f"Не удалось загрузить изображение: {image_path}")

    h, w, _ = image.shape
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    # Используем кэшированный landmarker (синглтон, delegate=CPU)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    landmarker = _get_hand_landmarker()
    result = landmarker.detect(mp_image)

    if not result.hand_landmarks:
        raise ValueError("MediaPipe: рука не обнаружена")

    landmarks = result.hand_landmarks[0]
    handedness = result.handedness[0][0].category_name if result.handedness else "Right"

    # ===================================================================
    # РАЗМЕРЫ ЛАДОНИ
    # ===================================================================
    # Ширина ладони: расстояние между INDEX_MCP и PINKY_MCP
    palm_left = _get_landmark(landmarks, INDEX_MCP)
    palm_right = _get_landmark(landmarks, PINKY_MCP)
    palm_width = _dist(palm_left, palm_right)

    # Высота ладони: расстояние от WRIST до MIDDLE_MCP
    wrist = _get_landmark(landmarks, WRIST)
    middle_mcp = _get_landmark(landmarks, MIDDLE_MCP)
    palm_height = _dist(wrist, middle_mcp)

    palm_w_to_h = round(palm_width / palm_height, 3) if palm_height > 0 else 0.0

    # ===================================================================
    # ДЛИНЫ ПАЛЬЦЕВ
    # ===================================================================
    thumb_len = _finger_length(landmarks, THUMB_TIP, THUMB_IP, THUMB_MCP, THUMB_CMC)
    index_len = _finger_length(landmarks, INDEX_TIP, INDEX_DIP, INDEX_PIP, INDEX_MCP)
    middle_len = _finger_length(landmarks, MIDDLE_TIP, MIDDLE_DIP, MIDDLE_PIP, MIDDLE_MCP)
    ring_len = _finger_length(landmarks, RING_TIP, RING_DIP, RING_PIP, RING_MCP)
    pinky_len = _finger_length(landmarks, PINKY_TIP, PINKY_DIP, PINKY_PIP, PINKY_MCP)

    # Нормализуем к высоте ладони
    def _norm(val: float) -> float:
        return round(val / palm_height, 3) if palm_height > 0 else 0.0

    # ===================================================================
    # СООТНОШЕНИЯ ПАЛЬЦЕВ (включая 2D:4D ratio)
    # ===================================================================
    index_to_ring = round(index_len / ring_len, 3) if ring_len > 0 else 0.0
    index_to_middle = round(index_len / middle_len, 3) if middle_len > 0 else 0.0
    ring_to_middle = round(ring_len / middle_len, 3) if middle_len > 0 else 0.0
    pinky_to_ring = round(pinky_len / ring_len, 3) if ring_len > 0 else 0.0
    thumb_to_index = round(thumb_len / index_len, 3) if index_len > 0 else 0.0

    # ===================================================================
    # УГЛЫ ПАЛЬЦЕВ
    # ===================================================================
    # Угол большого пальца (отставленность)
    thumb_cmc = _get_landmark(landmarks, THUMB_CMC)
    thumb_tip = _get_landmark(landmarks, THUMB_TIP)
    thumb_mcp_pt = _get_landmark(landmarks, THUMB_MCP)

    # Вектор от WRIST к INDEX_MCP (ось ладони)
    v_wrist_index = {"x": palm_left["x"] - wrist["x"], "y": palm_left["y"] - wrist["y"]}
    # Вектор от WRIST к THUMB_TIP
    v_wrist_thumb = {"x": thumb_tip["x"] - wrist["x"], "y": thumb_tip["y"] - wrist["y"]}
    thumb_angle = _angle_between_vectors(v_wrist_index, v_wrist_thumb)

    # Угол каждого пальца (отклонение от прямой)
    def _finger_angle(mcp_idx: int, pip_idx: int, dip_idx: int, tip_idx: int) -> float:
        """Угол между первой и второй фалангой пальца."""
        return _angle_three_points(
            _get_landmark(landmarks, mcp_idx),
            _get_landmark(landmarks, pip_idx),
            _get_landmark(landmarks, dip_idx),
        )

    index_angle = _angle_three_points(
        _get_landmark(landmarks, INDEX_MCP),
        _get_landmark(landmarks, INDEX_PIP),
        _get_landmark(landmarks, INDEX_DIP),
    )
    middle_angle = _angle_three_points(
        _get_landmark(landmarks, MIDDLE_MCP),
        _get_landmark(landmarks, MIDDLE_PIP),
        _get_landmark(landmarks, MIDDLE_DIP),
    )
    ring_angle = _angle_three_points(
        _get_landmark(landmarks, RING_MCP),
        _get_landmark(landmarks, RING_PIP),
        _get_landmark(landmarks, RING_DIP),
    )
    pinky_angle = _angle_three_points(
        _get_landmark(landmarks, PINKY_MCP),
        _get_landmark(landmarks, PINKY_PIP),
        _get_landmark(landmarks, PINKY_DIP),
    )

    # ===================================================================
    # КРИВИЗНА ПАЛЬЦЕВ
    # ===================================================================
    thumb_curv = _finger_curvature(landmarks, THUMB_TIP, THUMB_IP, THUMB_MCP, THUMB_CMC)
    index_curv = _finger_curvature(landmarks, INDEX_TIP, INDEX_DIP, INDEX_PIP, INDEX_MCP)
    middle_curv = _finger_curvature(landmarks, MIDDLE_TIP, MIDDLE_DIP, MIDDLE_PIP, MIDDLE_MCP)
    ring_curv = _finger_curvature(landmarks, RING_TIP, RING_DIP, RING_PIP, RING_MCP)
    pinky_curv = _finger_curvature(landmarks, PINKY_TIP, PINKY_DIP, PINKY_PIP, PINKY_MCP)

    # ===================================================================
    # РАЗВОДКА ПАЛЬЦЕВ
    # ===================================================================
    index_tip_pt = _get_landmark(landmarks, INDEX_TIP)
    middle_tip_pt = _get_landmark(landmarks, MIDDLE_TIP)
    ring_tip_pt = _get_landmark(landmarks, RING_TIP)
    pinky_tip_pt = _get_landmark(landmarks, PINKY_TIP)

    spread_index_middle = _dist(index_tip_pt, middle_tip_pt)
    spread_middle_ring = _dist(middle_tip_pt, ring_tip_pt)
    spread_ring_pinky = _dist(ring_tip_pt, pinky_tip_pt)

    avg_spread = (spread_index_middle + spread_middle_ring + spread_ring_pinky) / 3
    finger_spread_to_palm = round(avg_spread / palm_width, 3) if palm_width > 0 else 0.0

    # ===================================================================
    # ФОРМА ЛАДОНИ
    # ===================================================================
    palm_shape = _determine_palm_shape(palm_w_to_h, thumb_angle, finger_spread_to_palm)

    # ===================================================================
    # ДОМИНАНТНЫЙ ПАЛЕЦ
    # ===================================================================
    finger_lengths = {
        "thumb": thumb_len,
        "index": index_len,
        "middle": middle_len,
        "ring": ring_len,
        "pinky": pinky_len,
    }
    dominant_finger = max(finger_lengths, key=finger_lengths.get)

    # ===================================================================
    # СБОРКА РЕЗУЛЬТАТА
    # ===================================================================
    proportions = {
        "palm_width_to_height": palm_w_to_h,
        "handedness": handedness,
        "palm_shape": palm_shape,
        "dominant_finger": dominant_finger,
        "finger_ratios": {
            "index_to_ring_2D4D": index_to_ring,
            "index_to_middle": index_to_middle,
            "ring_to_middle": ring_to_middle,
            "pinky_to_ring": pinky_to_ring,
            "thumb_to_index": thumb_to_index,
        },
        "finger_lengths": {
            "thumb": _norm(thumb_len),
            "index": _norm(index_len),
            "middle": _norm(middle_len),
            "ring": _norm(ring_len),
            "pinky": _norm(pinky_len),
        },
        "finger_angles": {
            "thumb_angle": round(thumb_angle, 1),
            "index_pip": round(index_angle, 1),
            "middle_pip": round(middle_angle, 1),
            "ring_pip": round(ring_angle, 1),
            "pinky_pip": round(pinky_angle, 1),
        },
        "finger_curvature": {
            "thumb": thumb_curv,
            "index": index_curv,
            "middle": middle_curv,
            "ring": ring_curv,
            "pinky": pinky_curv,
        },
        "finger_spread": {
            "index_middle": round(spread_index_middle / palm_width, 3) if palm_width > 0 else 0.0,
            "middle_ring": round(spread_middle_ring / palm_width, 3) if palm_width > 0 else 0.0,
            "ring_pinky": round(spread_ring_pinky / palm_width, 3) if palm_width > 0 else 0.0,
            "avg_spread_to_palm": finger_spread_to_palm,
        },
        "details": {
            "palm": {
                "width": round(palm_width, 4),
                "height": round(palm_height, 4),
                "width_to_height": palm_w_to_h,
            },
            "fingers_raw": {
                "thumb_length": round(thumb_len, 4),
                "index_length": round(index_len, 4),
                "middle_length": round(middle_len, 4),
                "ring_length": round(ring_len, 4),
                "pinky_length": round(pinky_len, 4),
            },
        },
    }

    return {
        "proportions": proportions,
        "landmarks_raw": [_get_landmark(landmarks, i) for i in range(21)],
        "image_shape": {"h": h, "w": w},
    }


# ---------------------------------------------------------------------------
# Определение формы ладони
# ---------------------------------------------------------------------------
def _determine_palm_shape(w_to_h: float, thumb_angle: float, spread: float) -> str:
    if w_to_h > 0.95:
        return "квадратная, широкая"
    if w_to_h < 0.65:
        return "вытянутая, узкая"
    if thumb_angle > 50 and spread > 1.2:
        return "веерообразная, с отставленным большим пальцем"
    if w_to_h > 0.80:
        return "прямоугольная, сбалансированная"
    return "овальная, пропорциональная"


# ---------------------------------------------------------------------------
# Детекция линий ладони (Gabor + ridge detection)
# ---------------------------------------------------------------------------
def _detect_palm_lines(image_path: str, landmarks_raw: list, image_shape: dict) -> dict:
    """
    Детекция основных линий ладони через Gabor-фильтры и ridge detection.
    Использует ключевые точки для определения ROI-зон каждой линии.
    """
    image = cv2.imread(image_path)
    if image is None:
        return _palm_lines_stub()

    h, w = image_shape["h"], image_shape["w"]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Определяем ROI ладони по landmarks
    # Центр ладони
    palm_center = _midpoint(landmarks_raw[WRIST], landmarks_raw[MIDDLE_MCP])

    # Радиус ладони (для ROI)
    palm_radius = _dist(landmarks_raw[WRIST], landmarks_raw[MIDDLE_MCP]) * 0.8

    # Извлекаем ROI ладони
    cx, cy = int(palm_center["x"] * w), int(palm_center["y"] * h)
    r = int(palm_radius * min(w, h))
    r = max(r, 50)  # минимум 50 пикселей

    # Ограничиваем ROI рамками изображения
    x1 = max(0, cx - r)
    y1 = max(0, cy - r)
    x2 = min(w, cx + r)
    y2 = min(h, cy + r)

    roi = gray[y1:y2, x1:x2]
    if roi.size == 0:
        return _palm_lines_stub()

    # ===================================================================
    # Предобработка
    # ===================================================================
    # Усиление контраста (CLAHE)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    roi_enhanced = clahe.apply(roi)

    # Размытие для уменьшения шума
    roi_blur = cv2.GaussianBlur(roi_enhanced, (3, 3), 0)

    # ===================================================================
    # Gabor-фильтры для обнаружения борозд
    # ===================================================================
    gabor_responses = []
    for theta_deg in range(0, 180, 15):
        theta = theta_deg * math.pi / 180
        kernel = cv2.getGaborKernel(
            ksize=(15, 15),
            sigma=3.0,
            theta=theta,
            lambd=8.0,
            gamma=0.5,
            psi=0,
        )
        filtered = cv2.filter2D(roi_blur, cv2.CV_64F, kernel)
        gabor_responses.append(np.abs(filtered))

    # Суммарный отклик Gabor-фильтров
    gabor_sum = np.sum(gabor_responses, axis=0)
    gabor_norm = cv2.normalize(gabor_sum, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)

    # Бинаризация
    _, gabor_binary = cv2.threshold(gabor_norm, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # ===================================================================
    # Ridge detection через Hessian (как в scikit-image)
    # ===================================================================
    # Вычисляем Hessian через Sobel
    sobel_x = cv2.Sobel(roi_blur, cv2.CV_64F, 1, 0, ksize=3)
    sobel_y = cv2.Sobel(roi_blur, cv2.CV_64F, 0, 1, ksize=3)
    sobel_xx = cv2.Sobel(sobel_x, cv2.CV_64F, 1, 0, ksize=3)
    sobel_yy = cv2.Sobel(sobel_y, cv2.CV_64F, 0, 1, ksize=3)
    sobel_xy = cv2.Sobel(sobel_x, cv2.CV_64F, 0, 1, ksize=3)

    # Мера ridge: наименьшее собственное значение Hessian
    det_H = sobel_xx * sobel_yy - sobel_xy ** 2
    ridge_response = np.sqrt(np.maximum(det_H, 0))
    ridge_norm = cv2.normalize(ridge_response, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)

    # Объединяем Gabor и ridge
    combined = cv2.addWeighted(gabor_binary, 0.5, ridge_norm, 0.5, 0)
    _, combined_binary = cv2.threshold(combined, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # Морфологическое замыкание для связывания разрывов
    kernel_close = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    combined_clean = cv2.morphologyEx(combined_binary, cv2.MORPH_CLOSE, kernel_close)

    # ===================================================================
    # Определение характеристик линий по ROI-зонам
    # ===================================================================
    # Линия сердца: область под основаниями пальцев
    # Линия головы: средняя часть ладони
    # Линия жизни: вокруг большого пальца
    # Линия судьбы: вертикально через центр

    # Точки в координатах изображения
    def _to_img(lm):
        return {"x": lm["x"] * w, "y": lm["y"] * h}

    wrist_pt = _to_img(landmarks_raw[WRIST])
    index_mcp_pt = _to_img(landmarks_raw[INDEX_MCP])
    middle_mcp_pt = _to_img(landmarks_raw[MIDDLE_MCP])
    ring_mcp_pt = _to_img(landmarks_raw[RING_MCP])
    pinky_mcp_pt = _to_img(landmarks_raw[PINKY_MCP])
    thumb_mcp_pt = _to_img(landmarks_raw[THUMB_MCP])

    # Линия сердца: от INDEX_MCP до PINKY_MCP (горизонтальная верхняя зона)
    heart_zone = _extract_line_zone(
        combined_clean, x1, y1, x2, y2,
        index_mcp_pt, pinky_mcp_pt,
        offset_y=-int(palm_radius * min(w, h) * 0.15),
        zone_height=int(palm_radius * min(w, h) * 0.25),
    )

    # Линия головы: центр ладони, от.thumb_mcp до ring_mcp
    head_zone = _extract_line_zone(
        combined_clean, x1, y1, x2, y2,
        thumb_mcp_pt, ring_mcp_pt,
        offset_y=int(palm_radius * min(w, h) * 0.05),
        zone_height=int(palm_radius * min(w, h) * 0.25),
    )

    # Линия жизни: от thumb_mcp вниз к wrist
    life_zone = _extract_line_zone(
        combined_clean, x1, y1, x2, y2,
        thumb_mcp_pt, wrist_pt,
        offset_x=int(palm_radius * min(w, h) * 0.05),
        zone_width=int(palm_radius * min(w, h) * 0.30),
    )

    # Линия судьбы: вертикально через центр (middle_mcp → wrist)
    fate_zone = _extract_line_zone_vertical(
        combined_clean, x1, y1, x2, y2,
        middle_mcp_pt, wrist_pt,
        zone_width=int(palm_radius * min(w, h) * 0.20),
    )

    # Анализируем каждую зону
    heart_line = _analyze_line_zone(heart_zone, "heart")
    head_line = _analyze_line_zone(head_zone, "head")
    life_line = _analyze_line_zone(life_zone, "life")
    fate_line = _analyze_line_zone_vertical(fate_zone, "fate")

    return {
        "heart_line": heart_line,
        "head_line": head_line,
        "life_line": life_line,
        "fate_line": fate_line,
        "detection_method": "gabor_ridge_combined",
        "detection_available": True,
    }


def _extract_line_zone(binary_img, x1, y1, x2, y2, pt_a, pt_b,
                        offset_y=0, zone_height=None,
                        offset_x=0, zone_width=None) -> np.ndarray:
    """Извлечь горизонтальную зону из бинарного изображения."""
    h_img, w_img = binary_img.shape

    # Локальные координаты внутри ROI
    ax = int(pt_a["x"]) - x1
    ay = int(pt_a["y"]) - y1 + offset_y
    bx = int(pt_b["x"]) - x1
    by = int(pt_b["y"]) - y1 + offset_y

    # Ограничиваем
    ax = max(0, min(w_img - 1, ax))
    ay = max(0, min(h_img - 1, ay))
    bx = max(0, min(w_img - 1, bx))
    by = max(0, min(h_img - 1, by))

    if zone_height is None:
        zone_height = max(10, abs(by - ay) + 20)

    min_y = max(0, min(ay, by) - zone_height // 4)
    max_y = min(h_img, max(ay, by) + zone_height * 3 // 4)

    if zone_width is not None:
        center_x = (ax + bx) // 2
        min_x = max(0, center_x + offset_x - zone_width // 2)
        max_x = min(w_img, center_x + offset_x + zone_width // 2)
    else:
        min_x = min(ax, bx)
        max_x = max(ax, bx)

    min_x = max(0, min_x)
    max_x = min(w_img, max_x)

    zone = binary_img[min_y:max_y, min_x:max_x]
    return zone


def _extract_line_zone_vertical(binary_img, x1, y1, x2, y2, pt_top, pt_bottom,
                                 zone_width=None) -> np.ndarray:
    """Извлечь вертикальную зону из бинарного изображения."""
    h_img, w_img = binary_img.shape

    tx = int(pt_top["x"]) - x1
    ty = int(pt_top["y"]) - y1
    bx = int(pt_bottom["x"]) - x1
    by = int(pt_bottom["y"]) - y1

    tx = max(0, min(w_img - 1, tx))
    ty = max(0, min(h_img - 1, ty))
    bx = max(0, min(w_img - 1, bx))
    by = max(0, min(h_img - 1, by))

    if zone_width is None:
        zone_width = max(10, abs(tx - bx) + 20)

    center_x = (tx + bx) // 2
    min_x = max(0, center_x - zone_width // 2)
    max_x = min(w_img, center_x + zone_width // 2)
    min_y = min(ty, by)
    max_y = max(ty, by)

    zone = binary_img[min_y:max_y, min_x:max_x]
    return zone


def _analyze_line_zone(zone: np.ndarray, line_name: str) -> dict:
    """Анализ зоны линии: глубина, длина, кривизна, ветвление."""
    if zone.size == 0:
        return {"depth": 0.0, "length": "absent", "curvature": 0.0, "branching": False, "present": False}

    total_pixels = zone.size
    white_pixels = np.count_nonzero(zone)
    density = white_pixels / total_pixels if total_pixels > 0 else 0.0

    # Глубина (0-1) — плотность белых пикселей в зоне
    depth = round(min(1.0, density * 5), 3)  # масштабируем

    # Длина: определяем по горизонтальному/вертикальному покрытию
    if zone.shape[1] > 0:
        col_coverage = np.count_nonzero(np.sum(zone, axis=0)) / zone.shape[1]
        row_coverage = np.count_nonzero(np.sum(zone, axis=1)) / zone.shape[0]
        coverage = max(col_coverage, row_coverage)
    else:
        coverage = 0.0

    if coverage < 0.15:
        length = "absent"
        present = False
    elif coverage < 0.35:
        length = "short"
        present = True
    elif coverage < 0.60:
        length = "medium"
        present = True
    else:
        length = "long"
        present = True

    # Кривизна: определяем через вертикальное смещение центра масс по столбцам
    curvature = 0.0
    if present and zone.shape[1] > 2:
        centers = []
        for col in range(zone.shape[1]):
            rows = np.where(zone[:, col] > 0)[0]
            if len(rows) > 0:
                centers.append(np.mean(rows))
        if len(centers) > 2:
            # Вариация центров = мера кривизны
            centers_arr = np.array(centers)
            curvature = round(float(np.std(centers_arr) / max(1, zone.shape[0])), 3)

    # Ветвление: несколько отдельных компонент
    branching = False
    if present:
        num_labels, _ = cv2.connectedComponents(zone)
        branching = num_labels > 3

    return {
        "depth": depth,
        "length": length,
        "curvature": curvature,
        "branching": branching,
        "present": present,
    }


def _analyze_line_zone_vertical(zone: np.ndarray, line_name: str) -> dict:
    """Анализ вертикальной зоны линии (судьба)."""
    return _analyze_line_zone(zone, line_name)


def _palm_lines_stub() -> dict:
    return {
        "heart_line": {"depth": 0.0, "length": "absent", "curvature": 0.0, "branching": False, "present": False},
        "head_line": {"depth": 0.0, "length": "absent", "curvature": 0.0, "branching": False, "present": False},
        "life_line": {"depth": 0.0, "length": "absent", "curvature": 0.0, "branching": False, "present": False},
        "fate_line": {"depth": 0.0, "length": "absent", "curvature": 0.0, "branching": False, "present": False},
        "detection_method": "none",
        "detection_available": False,
    }


# ---------------------------------------------------------------------------
# Анализ кожи ладони
# ---------------------------------------------------------------------------
def _analyze_palm_skin(image_path: str, landmarks_raw: list, image_shape: dict) -> dict:
    """Анализ кожи ладони: тон, текстура, ровность."""
    image = cv2.imread(image_path)
    if image is None:
        return _skin_stub()

    h, w = image_shape["h"], image_shape["w"]
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

    # Создаём маску ладони по ключевым точкам
    palm_points = [
        WRIST, THUMB_CMC, THUMB_MCP,
        INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP,
    ]
    pts = np.array(
        [[int(landmarks_raw[i]["x"] * w), int(landmarks_raw[i]["y"] * h)] for i in palm_points],
        dtype=np.int32,
    )

    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.fillConvexPoly(mask, pts, 255)

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

    # Ровность
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if mask.sum() > 0:
        skin_gradient_x = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
        skin_gradient_y = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
        gradient_mag = np.sqrt(skin_gradient_x ** 2 + skin_gradient_y ** 2)
        skin_grad = gradient_mag[mask > 0]
        mean_grad = np.mean(skin_grad)
        roughness = round(min(1.0, mean_grad / 80), 3)
        smoothness = round(1.0 - roughness, 3)

        brightness_std = np.std(skin_pixels_hsv[:, 2]) / 255
        evenness = round(max(0, 1 - brightness_std * 3), 3)
    else:
        roughness = 0.5
        smoothness = 0.5
        evenness = 0.5

    return {
        "tone": {
            "hue": hue,
            "saturation": saturation,
            "brightness": brightness,
            "undertone": undertone,
        },
        "evenness": {
            "overall": evenness,
        },
        "texture": {
            "smoothness": smoothness,
            "roughness": roughness,
        },
        "segmentation_available": True,
        "_stub": False,
    }


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


def _skin_stub() -> dict:
    return {
        "tone": {"hue": 0.0, "saturation": 0.0, "brightness": 0.0, "undertone": "нейтральный"},
        "evenness": {"overall": 0.0},
        "texture": {"smoothness": 0.0, "roughness": 0.0},
        "segmentation_available": False,
        "_stub": True,
    }


# ---------------------------------------------------------------------------
# Публичный API
# ---------------------------------------------------------------------------
def analyze_palm(image_path: str, telegram_id: int | None = None) -> dict:
    """
    Полный анализ ладони из фото.

    Args:
        image_path: Путь к изображению ладони
        telegram_id: Telegram ID пользователя — для логирования контекста (опционально)

    Returns:
        dict с ключами: proportions, lines, skin
    """
    _ctx = f"tg={telegram_id} " if telegram_id else ""
    path = Path(image_path)
    if not path.exists():
        log.error("%sanalyze_palm: изображение не найдено: %s", _ctx, image_path)
        raise FileNotFoundError(f"Изображение не найдено: {image_path}")

    t0 = time.monotonic()
    log.info("%sanalyze_palm: старт", _ctx)

    # 1. Пропорции через MediaPipe HandLandmarker
    hand_result = _analyze_hand_landmarks(image_path)

    # 2. Линии ладони через Gabor + ridge
    lines_result = _detect_palm_lines(
        image_path,
        hand_result["landmarks_raw"],
        hand_result["image_shape"],
    )

    # 3. Кожа ладони
    skin_result = _analyze_palm_skin(
        image_path,
        hand_result["landmarks_raw"],
        hand_result["image_shape"],
    )

    elapsed = time.monotonic() - t0
    log.info("%sanalyze_palm: успешно за %.2fs (shape=%s, lines=%s)",
             _ctx, elapsed,
             hand_result["proportions"].get("palm_shape"),
             lines_result.get("detection_available"))

    return {
        "proportions": hand_result["proportions"],
        "lines": lines_result,
        "skin": skin_result,
    }