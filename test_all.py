"""
Тест всех трёх типов отчётов БЕЗ вызова LLM.
Использует эталонные блоки как заглушки.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.api import build_input_only
from src.core.renderer import render_template
from src.reports import self_report, couple_report, money_report


PROJECT_ROOT = Path(__file__).parent
EXAMPLES = PROJECT_ROOT / "examples"
TEMPLATES = PROJECT_ROOT / "src" / "templates"
OUTPUT = PROJECT_ROOT / "output"
OUTPUT.mkdir(exist_ok=True)


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


face_a = load(EXAMPLES / "sample_face_artem.json")
face_b = load(EXAMPLES / "sample_face_alina.json")


def test_self():
    target = build_input_only(
        "self", face_data=face_a, name="Артём", birthdate="28.01.1995", ref_year=2026,
    )
    blocks = load(EXAMPLES / "self" / "reference_blocks.json")
    html = render_template(TEMPLATES, "self_report.html.jinja", target, blocks)
    out = OUTPUT / "test_self.html"
    out.write_text(html, encoding="utf-8")
    print(f"✓ self  → {out} ({len(html):,} байт)")


def test_money():
    target = build_input_only(
        "money", face_data=face_a, name="Артём", birthdate="28.01.1995", ref_year=2026,
    )
    blocks = load(EXAMPLES / "money" / "reference_blocks.json")
    html = render_template(TEMPLATES, "money_report.html.jinja", target, blocks)
    out = OUTPUT / "test_money.html"
    out.write_text(html, encoding="utf-8")
    print(f"✓ money → {out} ({len(html):,} байт)")


def test_couple():
    target = build_input_only(
        "couple",
        face_data=face_a, name="Артём", birthdate="28.01.1995",
        face_data_b=face_b, name_b="Алина", birthdate_b="14.06.1997",
        ref_year=2026,
    )
    blocks = load(EXAMPLES / "couple" / "reference_blocks.json")
    html = render_template(TEMPLATES, "couple_report.html.jinja", target, blocks)
    out = OUTPUT / "test_couple.html"
    out.write_text(html, encoding="utf-8")
    print(f"✓ couple → {out} ({len(html):,} байт)")


def test_validators():
    """Проверим что эталоны проходят свои же валидаторы."""
    for name, mod, subdir in [
        ("self", self_report, "self"),
        ("couple", couple_report, "couple"),
        ("money", money_report, "money"),
    ]:
        blocks = load(EXAMPLES / subdir / "reference_blocks.json")
        errors = mod.validate_blocks(blocks)
        if errors:
            print(f"✗ {name} validator FAILED:")
            for e in errors:
                print(f"   - {e}")
        else:
            print(f"✓ {name} validator passed")


if __name__ == "__main__":
    print("=== Validators ===")
    test_validators()
    print("\n=== Renders ===")
    test_self()
    test_money()
    test_couple()
