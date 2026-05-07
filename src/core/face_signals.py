"""
Извлечение сигналов из неиспользуемых данных face JSON:
- blendshapes → мышечные паттерны лица
- deepface.emotions → эмоциональный профиль
- skin → сигналы кожи (roughness, evenness, зоны напряжения)
- asymmetry → асимметрия черт
- stylistic markers → серьги, пирсинг и т.д.
"""


# Пороги для blendshapes: значение выше → паттерн считается выраженным
BLENDSHAPE_THRESHOLDS = {
    "eyeBlinkLeft": {"threshold": 0.12, "label": "полуопущенное левое веко", "interpretation": "Усталость, сосредоточенность или привычка к наблюдению без внешней реакции"},
    "eyeBlinkRight": {"threshold": 0.12, "label": "полуопущенное правое веко", "interpretation": "Усталость, сосредоточенность или привычка к наблюдению без внешней реакции"},
    "browDownLeft": {"threshold": 0.20, "label": "нахмур бровей", "interpretation": "Хроническое напряжение лба — склонность к критике и контролю"},
    "browDownRight": {"threshold": 0.20, "label": "нахмур бровей", "interpretation": "Хроническое напряжение лба — склонность к критике и контролю"},
    "browInnerUp": {"threshold": 0.25, "label": "поднятые внутренние концы бровей", "interpretation": "Выраженная эмпатия, эмоциональная вовлечённость"},
    "browOuterUpLeft": {"threshold": 0.25, "label": "внешний подъём левой брови", "interpretation": "Скептицизм, привычка оценивать"},
    "browOuterUpRight": {"threshold": 0.25, "label": "внешний подъём правой брови", "interpretation": "Скептицизм, привычка оценивать"},
    "eyeSquintLeft": {"threshold": 0.30, "label": "аналитический прищур (левый)", "interpretation": "Привычка вглядываться, анализировать, не доверять первому впечатлению"},
    "eyeSquintRight": {"threshold": 0.30, "label": "аналитический прищур (правый)", "interpretation": "Привычка вглядываться, анализировать, не доверять первому впечатлению"},
    "eyeWideLeft": {"threshold": 0.30, "label": "расширенный левый глаз", "interpretation": "Открытость восприятию, готовность к новому"},
    "eyeWideRight": {"threshold": 0.30, "label": "расширенный правый глаз", "interpretation": "Открытость восприятию, готовность к новому"},
    "mouthPressLeft": {"threshold": 0.05, "label": "сжатые губы", "interpretation": "Сдержанность в речи, привычка держать при себе"},
    "mouthPressRight": {"threshold": 0.05, "label": "сжатые губы", "interpretation": "Сдержанность в речи, привычка держать при себе"},
    "mouthPucker": {"threshold": 0.05, "label": "поджатые губы", "interpretation": "Недовольство, подавленная критика"},
    "mouthRollLower": {"threshold": 0.05, "label": "зажатая нижняя губа", "interpretation": "Контроль над эмоциями, внутренний протест"},
    "mouthRollUpper": {"threshold": 0.05, "label": "поджатая верхняя губа", "interpretation": "Внутреннее удержание эмоций, осторожность в словах"},
    "mouthFrownLeft": {"threshold": 0.10, "label": "опущенный уголок рта", "interpretation": "Склонность к пессимизму, фоновое недовольство"},
    "mouthFrownRight": {"threshold": 0.10, "label": "опущенный уголок рта", "interpretation": "Склонность к пессимизму, фоновое недовольство"},
    "mouthSmileLeft": {"threshold": 0.15, "label": "левая полуулыбка", "interpretation": "Ироничность, неоднозначное отношение к ситуации"},
    "mouthSmileRight": {"threshold": 0.15, "label": "правая полуулыбка", "interpretation": "Ироничность, неоднозначное отношение к ситуации"},
    "chinRaiserLower": {"threshold": 0.15, "label": "напряжённый подбородок", "interpretation": "Упрямство, сопротивление давлению"},
    "noseSneerLeft": {"threshold": 0.10, "label": "кривой нос (лево)", "interpretation": "Презрение, неприятие — микровыражение отвращения"},
    "noseSneerRight": {"threshold": 0.10, "label": "кривой нос (право)", "interpretation": "Презрение, неприятие — микровыражение отвращения"},
    "jawOpen": {"threshold": 0.20, "label": "расслабленная челюсть", "interpretation": "Расслабленность, открытость, отсутствие контроля"},
    "jawForward": {"threshold": 0.10, "label": "выдвинутая челюсть", "interpretation": "Агрессивная позиция, готовность к конфликту"},
    "cheekSquintLeft": {"threshold": 0.25, "label": "напряжённая щека (лево)", "interpretation": "Сдерживаемая эмоция, привычка контролировать мимику"},
    "cheekSquintRight": {"threshold": 0.25, "label": "напряжённая щека (право)", "interpretation": "Сдерживаемая эмоция, привычка контролировать мимику"},
}

# Перевод английских названий эмоций DeepFace → русский
EMOTION_NAMES_RU = {
    "neutral": "нейтральный",
    "sad": "грусть",
    "angry": "гнев",
    "disgust": "отвращение",
    "surprise": "удивление",
    "fear": "страх",
    "happy": "радость",
}

# Интерпретации эмоций
EMOTION_INTERPRETATIONS = {
    "neutral": "Внутреннее спокойствие или отключённость — лицо «по умолчанию»",
    "sad": "Фоновая грусть или усталость — тяжелые веки, опущенные уголки",
    "angry": "Подавленное раздражение — напряжение в челюсти и лбу",
    "disgust": "Неприятие — микровыражение отвращения в зоне носо-губной складки",
    "surprise": "Неожиданность — расширенные глаза, поднятые брови",
    "fear": "Тревога — напряжение вокруг глаз, стиснутые губы",
    "happy": "Позитив — расслабленные мышцы, приподнятые уголки рта",
}

# Интерпретации roughness кожи
def _interpret_roughness(value: float) -> dict:
    if value > 0.80:
        return {"label": "высокая шероховатость", "interpretation": "Признак хронической усталости, стресса или возрастных изменений — кожа несёт следы нагрузки"}
    if value > 0.50:
        return {"label": "умеренная шероховатость", "interpretation": "Нормальное состояние взрослой кожи — есть текстура, но без выраженных признаков истощения"}
    return {"label": "гладкая кожа", "interpretation": "Свежая, ухоженная кожа — признак хорошего восстановления и заботы о себе"}

# Интерпретации evenness по зонам
def _interpret_evenness(zone: str, value: float) -> str:
    if value > 0.30:
        return f"{zone}: выраженная неровность ({value:.2f}) — зона накопленного напряжения"
    if value > 0.20:
        return f"{zone}: умеренная неровность ({value:.2f})"
    return f"{zone}: ровная зона ({value:.2f})"


def extract_emotional_profile(emotions: dict) -> dict:
    """Извлекает топ-3 эмоции с интерпретациями."""
    sorted_emotions = sorted(emotions.items(), key=lambda x: x[1], reverse=True)
    top = sorted_emotions[:3]

    top_list = []
    for emotion, value in top:
        top_list.append({
            "emotion": EMOTION_NAMES_RU.get(emotion, emotion),
            "value": round(value, 1),
            "interpretation": EMOTION_INTERPRETATIONS.get(emotion, "")
        })

    dominant = top[0][0]
    dominant_val = top[0][1]
    dominant_ru = EMOTION_NAMES_RU.get(dominant, dominant)

    # Формируем summary
    if dominant == "neutral" and dominant_val > 70:
        summary = "Лицо «по умолчанию» — доминирует нейтральное выражение. Возможна внутренняя отстранённость или высокий самоконтроль"
    elif dominant == "sad" and dominant_val > 20:
        summary = "Фоновая грусть просачивается через нейтральную маску — тяжелые веки, опущенные уголки"
    elif dominant == "angry" and dominant_val > 15:
        summary = "Подавленное раздражение — челюсть и лоб выдают напряжение, которое лицо пытается скрыть"
    elif dominant == "happy" and dominant_val > 30:
        summary = "Естественная позитивность — мышцы лица привыкли к расслаблению и улыбке"
    else:
        summary = f"Доминирующая эмоция — {dominant_ru} ({dominant_val:.1f}%), но лицо контролирует выражение"

    return {
        "dominant": dominant_ru,
        "top": top_list,
        "summary": summary,
    }


def extract_muscle_patterns(blendshapes: dict) -> list:
    """Извлекает выраженные мышечные паттерны из blendshapes."""
    patterns = []

    for bs_name, config in BLENDSHAPE_THRESHOLDS.items():
        value = blendshapes.get(bs_name, 0.0)
        threshold = config["threshold"]

        if value >= threshold:
            patterns.append({
                "name": bs_name,
                "value": round(value, 3),
                "threshold": threshold,
                "label": config["label"],
                "interpretation": config["interpretation"],
            })

    # Группируем симметричные пары (лево/право)
    merged = _merge_symmetric_patterns(patterns)
    return sorted(merged, key=lambda x: x["value"], reverse=True)


def _merge_symmetric_patterns(patterns: list) -> list:
    """Объединяет левые/правые пары в одну запись с усреднённым значением."""
    pairs = {
        "eyeBlink": ("eyeBlinkLeft", "eyeBlinkRight"),
        "browDown": ("browDownLeft", "browDownRight"),
        "browOuterUp": ("browOuterUpLeft", "browOuterUpRight"),
        "eyeSquint": ("eyeSquintLeft", "eyeSquintRight"),
        "eyeWide": ("eyeWideLeft", "eyeWideRight"),
        "mouthPress": ("mouthPressLeft", "mouthPressRight"),
        "mouthFrown": ("mouthFrownLeft", "mouthFrownRight"),
        "mouthSmile": ("mouthSmileLeft", "mouthSmileRight"),
        "noseSneer": ("noseSneerLeft", "noseSneerRight"),
        "cheekSquint": ("cheekSquintLeft", "cheekSquintRight"),
    }

    by_name = {p["name"]: p for p in patterns}
    merged = []
    used = set()

    for combined_name, (left, right) in pairs.items():
        left_p = by_name.get(left)
        right_p = by_name.get(right)

        if left_p and right_p:
            avg_val = (left_p["value"] + right_p["value"]) / 2
            merged.append({
                "name": combined_name,
                "value": round(avg_val, 3),
                "label": left_p["label"].replace(" (левый)", "").replace(" (правый)", "").replace(" (лево)", "").replace(" (право)", ""),
                "interpretation": left_p["interpretation"],
            })
            used.add(left)
            used.add(right)
        elif left_p:
            merged.append(left_p)
            used.add(left)
        elif right_p:
            merged.append(right_p)
            used.add(right)

    # Добавляем непарные
    for p in patterns:
        if p["name"] not in used:
            merged.append(p)

    return merged


def extract_skin_signals(skin_data: dict) -> dict:
    """Извлекает сигналы кожи."""
    texture = skin_data.get("texture", {})
    roughness = texture.get("roughness", 0.0)
    rough_info = _interpret_roughness(roughness)

    evenness = skin_data.get("evenness", {})
    by_zone = evenness.get("by_zone", {})

    zone_signals = []
    tension_zones = []
    for zone, value in by_zone.items():
        zone_name = {
            "forehead": "лоб",
            "nose": "нос",
            "cheeks": "щёки",
            "left_cheek": "левая щека",
            "right_cheek": "правая щека",
            "chin": "подбородок",
            "around_eyes": "вокруг глаз",
        }.get(zone, zone)
        desc = _interpret_evenness(zone_name, value)
        zone_signals.append(desc)
        if value > 0.25:
            tension_zones.append(zone_name)

    # Summary
    parts = [f"Шероховатость: {rough_info['label']}"]
    if tension_zones:
        parts.append(f"Зоны напряжения: {', '.join(tension_zones)}")
    summary = ". ".join(parts)

    return {
        "roughness": {"value": round(roughness, 3), "label": rough_info["label"], "interpretation": rough_info["interpretation"]},
        "zone_signals": zone_signals,
        "tension_zones": tension_zones,
        "summary": summary,
    }


def extract_asymmetry_signals(details: dict) -> list:
    """Извлекает сигналы асимметрии с интерпретациями."""
    asym = details.get("asymmetry", {})
    signals = []

    brow_asym = asym.get("brow_asymmetry", 0.0)
    if brow_asym > 0.020:
        signals.append({
            "name": "brow_asymmetry",
            "value": round(brow_asym, 4),
            "label": "заметная асимметрия бровей",
            "interpretation": "Разница между внутренним посылом и внешним проявлением — одно лицо для мира, другое для себя"
        })
    elif brow_asym > 0.012:
        signals.append({
            "name": "brow_asymmetry",
            "value": round(brow_asym, 4),
            "label": "лёгкая асимметрия бровей",
            "interpretation": "Небольшой дисбаланс между логикой и эмоциями"
        })

    eye_asym = asym.get("eye_asymmetry", 0.0)
    if eye_asym > 0.015:
        signals.append({
            "name": "eye_asymmetry",
            "value": round(eye_asym, 4),
            "label": "заметная асимметрия глаз",
            "interpretation": "Разная степень открытости к миру — одно лицо публичное, другое личное"
        })

    return signals


def extract_stylistic_markers(skin_data: dict) -> list:
    """Извлекает стилистические маркеры (серьги, пирсинг и т.д.)."""
    markers = []
    zones_area = skin_data.get("zones_area", {})

    ear_ring = zones_area.get("ear_ring", 0.0)
    if ear_ring > 0.12:
        markers.append({
            "name": "ear_ring",
            "value": round(ear_ring, 3),
            "label": "серьга",
            "interpretation": "Маркер самовыражения — человек не боится выделяться, добавляет лицу акцент"
        })

    return markers


def extract_face_signals(face_data: dict) -> dict:
    """Главная функция: извлекает все сигналы из face_data."""
    deepface = face_data.get("deepface", {})
    proportions = face_data.get("proportions", {})
    details = proportions.get("details", {})
    skin = face_data.get("skin", {})

    # Эмоциональный профиль
    emotions = deepface.get("emotions", {})
    emotional_profile = extract_emotional_profile(emotions) if emotions else None

    # Мышечные паттерны
    blendshapes = proportions.get("blendshapes", {})
    muscle_patterns = extract_muscle_patterns(blendshapes) if blendshapes else []

    # Сигналы кожи
    skin_signals = extract_skin_signals(skin) if skin else None

    # Асимметрия
    asymmetry_signals = extract_asymmetry_signals(details)

    # Стилистические маркеры
    stylistic_markers = extract_stylistic_markers(skin)

    return {
        "emotional_profile": emotional_profile,
        "muscle_patterns": muscle_patterns,
        "skin_signals": skin_signals,
        "asymmetry_signals": asymmetry_signals,
        "stylistic_markers": stylistic_markers,
    }