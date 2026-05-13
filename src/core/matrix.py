"""
Матрица судьбы (расширенная Ладини).
13 позиций: 6 базовых + 7 зон жизни (деньги, любовь, здоровье, миссия,
духовный путь, творчество, комфорт).
"""
from .numerology import reduce_number


def _matrix_number(a: int, b: int) -> int:
    s = a + b
    while s > 22:
        s = reduce_number(s, keep_master=False)  # ← False, не допускаем зависания
    return s if s != 0 else 22

def calculate_matrix(birthdate: str) -> dict:
    """
    Расширенная матрица Ладини: 13 позиций по дате рождения.

    Базовая линия (6):
      personality     — Личность (центр)
      realization     — Реализация
      destiny         — Предназначение
      karma_rod       — Карма рода
      family_program  — Родовая программа
      challenge       — Главное испытание

    Зоны жизни (7):
      money           — Зона денег
      love            — Зона любви
      health          — Зона здоровья
      mission         — Зона миссии
      spiritual_path  — Духовный путь
      creativity      — Зона творчества
      comfort         — Зона комфорта
    """
    day, month, year = (int(x) for x in birthdate.split("."))
    d, m, y = reduce_number(day), reduce_number(month), reduce_number(year)

    # ── базовая линия (6 позиций) ──────────────────────────
    personality    = _matrix_number(d, m)
    realization    = _matrix_number(m, y)
    destiny        = _matrix_number(personality, realization)
    karma_rod      = _matrix_number(d, y)
    family_program = _matrix_number(personality, karma_rod)
    challenge      = _matrix_number(destiny, family_program)

    # ── зоны жизни (7 позиций) ─────────────────────────────
    # Вычисляются как перекрёстные комбинации базовых точек,
    # каждая зона — пересечение двух энергий.
    money          = _matrix_number(personality, destiny)
    love           = _matrix_number(personality, realization)
    health         = _matrix_number(personality, challenge)
    mission        = _matrix_number(destiny, karma_rod)
    spiritual_path = _matrix_number(family_program, challenge)
    creativity     = _matrix_number(realization, karma_rod)
    comfort        = _matrix_number(personality, family_program)

    return {
        # базовая линия
        "personality":     personality,
        "realization":     realization,
        "destiny":         destiny,
        "karma_rod":       karma_rod,
        "family_program":  family_program,
        "challenge":       challenge,
        # зоны жизни
        "money":           money,
        "love":            love,
        "health":          health,
        "mission":         mission,
        "spiritual_path":  spiritual_path,
        "creativity":      creativity,
        "comfort":         comfort,
    }
