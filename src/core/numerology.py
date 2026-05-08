"""
Нумерология: пифагорейская система.
Все расчёты детерминированные, без LLM.
"""
from datetime import datetime


def reduce_number(n: int, keep_master: bool = True) -> int:
    """Сводит число к одной цифре, сохраняя мастер-числа 11/22/33."""
    while n > 9:
        if keep_master and n in (11, 22, 33):
            return n
        n = sum(int(d) for d in str(n))
    return n


def parse_birthdate(birthdate: str) -> tuple[int, int, int]:
    """Парсит '28.01.1995' → (28, 1, 1995)."""
    dt = datetime.strptime(birthdate, "%d.%m.%Y")
    return dt.day, dt.month, dt.year


def life_path_number(birthdate: str) -> int:
    """Число жизненного пути = сумма всех цифр даты."""
    digits = [int(d) for d in birthdate if d.isdigit()]
    return reduce_number(sum(digits))


def day_number(birthdate: str) -> dict:
    """День рождения и его сведённое значение."""
    day, _, _ = parse_birthdate(birthdate)
    return {"day": day, "reduced": reduce_number(day)}


def personal_year(birthdate: str, year: int) -> int:
    """Личный год = день + месяц + год_расчёта, сведённый."""
    day, month, _ = parse_birthdate(birthdate)
    return reduce_number(sum(int(d) for d in f"{day}{month}{year}"))


def calculate_pinnacles(birthdate: str) -> list[dict]:
    """
    4 пинакла (периода жизни) по пифагорейской системе.
    Возрасты переходов зависят от числа жизненного пути.
    """
    day, month, year = parse_birthdate(birthdate)
    lp = life_path_number(birthdate)

    p1 = reduce_number(reduce_number(month) + reduce_number(day))
    p2 = reduce_number(reduce_number(day) + reduce_number(year))
    p3 = reduce_number(p1 + p2)
    p4 = reduce_number(reduce_number(month) + reduce_number(year))

    first_end = 36 - lp
    return [
        {"number": p1, "age_start": 0, "age_end": first_end},
        {"number": p2, "age_start": first_end, "age_end": first_end + 9},
        {"number": p3, "age_start": first_end + 9, "age_end": first_end + 18},
        {"number": p4, "age_start": first_end + 18, "age_end": None},
    ]


def calculate_age(birthdate: str, ref_year: int = None) -> int:
    """Возраст на указанную дату.

    Без ref_year — точный возраст на текущую дату (с учётом месяца и дня).
    С ref_year — возраст на конец указанного года (для нумерологических расчётов).
    """
    if ref_year is None:
        today = datetime.now()
        bday = datetime.strptime(birthdate, "%d.%m.%Y")
        return today.year - bday.year - (
            (today.month, today.day) < (bday.month, bday.day)
        )
    _, _, year = parse_birthdate(birthdate)
    return ref_year - year


def full_numerology_profile(birthdate: str, ref_year: int = None) -> dict:
    """Полный нумерологический профиль для отчёта."""
    if ref_year is None:
        ref_year = datetime.now().year

    return {
        "life_path": life_path_number(birthdate),
        "day": day_number(birthdate),
        "personal_year": {
            "year": ref_year,
            "number": personal_year(birthdate, ref_year),
        },
        "pinnacles": calculate_pinnacles(birthdate),
        "age": calculate_age(birthdate),
        "formula": _build_formula(birthdate),
    }


def _build_formula(birthdate: str) -> dict:
    """Текст формулы для отчёта (для прозрачности)."""
    digits = [d for d in birthdate if d.isdigit()]
    total = sum(int(d) for d in digits)

    # Полный путь редукции
    steps = [str(total)]
    cur = total
    while cur > 9 and cur not in (11, 22, 33):
        digit_sum_str = " + ".join(str(d) for d in str(cur))
        cur = sum(int(d) for d in str(cur))
        steps.append(f"{digit_sum_str} = {cur}")

    life_path_formula = f"{' + '.join(digits)} = {steps[0]}"
    if len(steps) > 1:
        life_path_formula += " → " + " → ".join(steps[1:])

    day, _, _ = parse_birthdate(birthdate)
    if day <= 9:
        day_steps = f"{day}"
    else:
        day_digits = " + ".join(str(d) for d in str(day))
        day_steps = f"{day} → {day_digits} = {reduce_number(day)}"

    return {
        "life_path": life_path_formula,
        "day": day_steps,
    }
