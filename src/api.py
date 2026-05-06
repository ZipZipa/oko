"""
Главная точка входа для всех типов отчётов.

Использование:
    from src.api import generate_report

    html = generate_report(
        report_type="self",
        face_data=face_a,
        name="Артём",
        birthdate="28.01.1995",
    )

    html = generate_report(
        report_type="couple",
        face_data=face_a, name="Артём", birthdate="28.01.1995",
        face_data_b=face_b, name_b="Алина", birthdate_b="14.06.1997",
    )

    html = generate_report(
        report_type="money",
        face_data=face_a,
        name="Артём",
        birthdate="28.01.1995",
    )
"""
from pathlib import Path

from .reports import self_report, couple_report, money_report


PROJECT_ROOT = Path(__file__).parent.parent
EXAMPLES_DIR = PROJECT_ROOT / "examples"
TEMPLATES_DIR = PROJECT_ROOT / "src" / "templates"


def generate_report(
    report_type: str,
    face_data: dict,
    name: str,
    birthdate: str,
    face_data_b: dict = None,
    name_b: str = None,
    birthdate_b: str = None,
    ref_year: int = None,
    model: str = None,
    palm_data: dict = None,
    photo_url: str = None,
) -> str:
    """
    Генерирует HTML отчёта одного из трёх типов.

    report_type: "self" | "couple" | "money"

    Для self и money — нужны face_data, name, birthdate.
    Для couple — дополнительно face_data_b, name_b, birthdate_b.
    palm_data — опциональные данные ладони (только для self).
    photo_url — опциональный URL или data URI фото пользователя (для self).
    """
    if report_type == "self":
        return self_report.generate(
            face_data=face_data, name=name, birthdate=birthdate,
            examples_dir=EXAMPLES_DIR, templates_dir=TEMPLATES_DIR,
            ref_year=ref_year, model=model, palm_data=palm_data,
        )

    elif report_type == "money":
        return money_report.generate(
            face_data=face_data, name=name, birthdate=birthdate,
            examples_dir=EXAMPLES_DIR, templates_dir=TEMPLATES_DIR,
            ref_year=ref_year, model=model,
        )

    elif report_type == "couple":
        if face_data_b is None or name_b is None or birthdate_b is None:
            raise ValueError("couple report requires face_data_b, name_b, birthdate_b")
        return couple_report.generate(
            face_a=face_data, name_a=name, birthdate_a=birthdate,
            face_b=face_data_b, name_b=name_b, birthdate_b=birthdate_b,
            examples_dir=EXAMPLES_DIR, templates_dir=TEMPLATES_DIR,
            ref_year=ref_year, model=model,
        )

    else:
        raise ValueError(f"Unknown report_type: {report_type}. Use 'self', 'couple', or 'money'.")


def build_input_only(report_type: str, **kwargs) -> dict:
    """
    Собирает target_input БЕЗ вызова LLM — для отладки.
    """
    if report_type == "self":
        return self_report.build_target_input(
            kwargs["face_data"], kwargs["name"], kwargs["birthdate"],
            kwargs.get("ref_year"), kwargs.get("palm_data"),
        )
    elif report_type == "money":
        return money_report.build_target_input(
            kwargs["face_data"], kwargs["name"], kwargs["birthdate"],
            kwargs.get("ref_year"),
        )
    elif report_type == "couple":
        return couple_report.build_target_input(
            kwargs["face_data"], kwargs["name"], kwargs["birthdate"],
            kwargs["face_data_b"], kwargs["name_b"], kwargs["birthdate_b"],
            kwargs.get("ref_year"),
        )
    else:
        raise ValueError(f"Unknown report_type: {report_type}")
