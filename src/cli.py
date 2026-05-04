"""
CLI для всех трёх типов отчётов.

Self:
  python -m src.cli self \\
    --face examples/sample_face_artem.json \\
    --name "Артём" --birthdate 28.01.1995 \\
    --output output/self.html

Money:
  python -m src.cli money \\
    --face examples/sample_face_artem.json \\
    --name "Артём" --birthdate 28.01.1995 \\
    --output output/money.html

Couple:
  python -m src.cli couple \\
    --face examples/sample_face_artem.json --name "Артём" --birthdate 28.01.1995 \\
    --face-b examples/sample_face_alina.json --name-b "Алина" --birthdate-b 14.06.1997 \\
    --output output/couple.html
"""
import argparse
import json
import sys
from pathlib import Path

from .api import generate_report


def main():
    parser = argparse.ArgumentParser(description="Генератор отчётов (self / couple / money)")
    parser.add_argument("report_type", choices=["self", "couple", "money"],
                        help="Тип отчёта")
    parser.add_argument("--face", required=True, help="JSON лица первого человека")
    parser.add_argument("--name", required=True)
    parser.add_argument("--birthdate", required=True, help="ДД.ММ.ГГГГ")
    parser.add_argument("--face-b", help="JSON лица второго (для couple)")
    parser.add_argument("--name-b")
    parser.add_argument("--birthdate-b")
    parser.add_argument("--output", default="output/report.html")
    parser.add_argument("--ref-year", type=int, default=None)
    parser.add_argument("--model", default=None)
    args = parser.parse_args()

    with open(args.face, encoding="utf-8") as f:
        face_data = json.load(f)

    kwargs = {
        "report_type": args.report_type,
        "face_data": face_data,
        "name": args.name,
        "birthdate": args.birthdate,
        "ref_year": args.ref_year,
        "model": args.model,
    }

    if args.report_type == "couple":
        if not args.face_b or not args.name_b or not args.birthdate_b:
            print("Для couple нужны --face-b, --name-b, --birthdate-b", file=sys.stderr)
            sys.exit(1)
        with open(args.face_b, encoding="utf-8") as f:
            face_b = json.load(f)
        kwargs.update({
            "face_data_b": face_b,
            "name_b": args.name_b,
            "birthdate_b": args.birthdate_b,
        })

    print(f"Генерирую {args.report_type} отчёт для {args.name}...")
    html = generate_report(**kwargs)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    print(f"Готово: {output_path}")


if __name__ == "__main__":
    main()
