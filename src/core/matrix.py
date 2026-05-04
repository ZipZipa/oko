"""
Матрица судьбы по методу Натальи Ладини (22 аркана Таро).
Чистая математика над датой.
"""
from .numerology import parse_birthdate


def reduce_to_arcana(n: int) -> int:
    """Сводит число к диапазону 1-22 (старшие арканы)."""
    while n > 22:
        n = sum(int(d) for d in str(n))
        if n == 0:
            return 22
    return n if n > 0 else 22


def calculate_matrix(birthdate: str) -> dict:
    """
    Базовый расчёт центральных позиций матрицы.

    Метод Ладини (упрощённый, основные позиции):
    - Личность (центр): день рождения, сведённый к арканам
    - Реализация: месяц рождения
    - Предназначение: личность + реализация
    - Карма рода: год рождения
    - Родовая программа: сумма цифр года
    - Главное испытание: сведённая сумма дня и года
    """
    day, month, year = parse_birthdate(birthdate)

    personality = reduce_to_arcana(day)
    realization = reduce_to_arcana(month)
    destiny = reduce_to_arcana(personality + realization)

    year_sum = sum(int(d) for d in str(year))
    karma_rod = reduce_to_arcana(year_sum)

    family_program = reduce_to_arcana(reduce_to_arcana(year_sum) + reduce_to_arcana(month))
    challenge = reduce_to_arcana(personality + karma_rod)

    return {
        "personality": personality,
        "realization": realization,
        "destiny": destiny,
        "karma_rod": karma_rod,
        "family_program": family_program,
        "challenge": challenge,
    }
