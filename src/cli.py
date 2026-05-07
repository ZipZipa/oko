"""
CLI: анализ лица/ладони + генерация отчётов.

Analyze face (DeepFace + MediaPipe → JSON):
  python -m src.cli analyze --image photo.jpg --output face.json

Analyze palm (MediaPipe HandLandmarker + Gabor/Ridge → JSON):
  python -m src.cli palm --image palm.jpg --output palm.json

Self:
  python -m src.cli report self \
    --face examples/sample_face_artem.json \
    --name "Артём" --birthdate 28.01.1995 \
    --photo examples/photo.jpeg \
    --output output/self.html

Self (без LLM, по референсу):
  python -m src.cli report self \
    --face examples/sample_face_artem.json \
    --name "Артём" --birthdate 28.01.1995 \
    --photo examples/photo.jpeg \
    --palm examples/sample_palm_artem.json \
    --reference examples/self/reference_blocks.json \
    --output output/self.html

Money:
  python -m src.cli report money \
    --face examples/sample_face_artem.json \
    --name "Артём" --birthdate 28.01.1995 \
    --output output/money.html

Couple:
  python -m src.cli report couple \
    --face examples/sample_face_artem.json --name "Артём" --birthdate 28.01.1995 \
    --face-b examples/sample_face_alina.json --name-b "Алина" --birthdate-b 14.06.1997 \
    --output output/couple.html
"""
import argparse
import base64
import json
import sys
from pathlib import Path

from .api import generate_report


def cmd_analyze(args):
    """Команда анализа лица из фото."""
    from .core.face_analyzer import analyze_face

    print(f"Анализирую лицо: {args.image} ...")
    try:
        result = analyze_face(args.image, deepface_detector=args.detector)
    except Exception as e:
        print(f"Ошибка анализа: {e}", file=sys.stderr)
        sys.exit(1)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Готово: {output_path}")


def cmd_palm(args):
    """Команда анализа ладони из фото."""
    from .core.palm_analyzer import analyze_palm

    print(f"Анализирую ладонь: {args.image} ...")
    try:
        result = analyze_palm(args.image)
    except Exception as e:
        print(f"Ошибка анализа: {e}", file=sys.stderr)
        sys.exit(1)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Готово: {output_path}")


def _photo_to_data_uri(path: str) -> str:
    """Кодирует фото в base64 data URI для встраивания в HTML."""
    photo_path = Path(path)
    ext = photo_path.suffix.lower().lstrip(".")
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
            "gif": "image/gif", "webp": "image/webp"}.get(ext, "image/jpeg")
    data = base64.b64encode(photo_path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def cmd_report(args):
    """Команда генерации отчёта."""
    with open(args.face, encoding="utf-8") as f:
        face_data = json.load(f)

    # Если передано фото — встраиваем как base64 data URI в face_data
    if args.photo:
        face_data["photo_url"] = _photo_to_data_uri(args.photo)

    kwargs = {
        "report_type": args.report_type,
        "face_data": face_data,
        "name": args.name,
        "birthdate": args.birthdate,
        "ref_year": args.ref_year,
        "model": args.model,
        "plan": args.plan,
        "reference": getattr(args, "reference", None),
    }

    if args.report_type == "self":
        if args.palm_left:
            with open(args.palm_left, encoding="utf-8") as f:
                kwargs["palm_data_left"] = json.load(f)
        if args.palm_right:
            with open(args.palm_right, encoding="utf-8") as f:
                kwargs["palm_data_right"] = json.load(f)

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


def main():
    parser = argparse.ArgumentParser(description="OKO — анализ лица и генерация отчётов")
    subparsers = parser.add_subparsers(dest="command")

    # --- analyze ---
    p_analyze = subparsers.add_parser("analyze", help="Анализ лица из фото (DeepFace + MediaPipe)")
    p_analyze.add_argument("--image", required=True, help="Путь к фотографии")
    p_analyze.add_argument("--output", default="face_analysis.json", help="Выходной JSON")
    p_analyze.add_argument("--detector", default="retinaface",
                           choices=["retinaface", "opencv", "ssd", "mtcnn", "skip"],
                           help="Детектор лиц для DeepFace")

    # --- palm ---
    p_palm = subparsers.add_parser("palm", help="Анализ ладони из фото (MediaPipe HandLandmarker + Gabor/Ridge)")
    p_palm.add_argument("--image", required=True, help="Путь к фотографии ладони")
    p_palm.add_argument("--output", default="palm_analysis.json", help="Выходной JSON")

    # --- report ---
    p_report = subparsers.add_parser("report", help="Генерация отчёта (self / couple / money)")
    p_report.add_argument("report_type", choices=["self", "couple", "money"],
                          help="Тип отчёта")
    p_report.add_argument("--face", required=True, help="JSON лица первого человека")
    p_report.add_argument("--name", required=True)
    p_report.add_argument("--birthdate", required=True, help="ДД.ММ.ГГГГ")
    p_report.add_argument("--face-b", help="JSON лица второго (для couple)")
    p_report.add_argument("--name-b")
    p_report.add_argument("--birthdate-b")
    p_report.add_argument("--output", default="output/report.html")
    p_report.add_argument("--palm-left", default=None, dest="palm_left", help="JSON левой ладони (для self, план full)")
    p_report.add_argument("--palm-right", default=None, dest="palm_right", help="JSON правой ладони (для self, план full)")
    p_report.add_argument("--photo", default=None, help="Фото для обложки отчёта (JPG/PNG)")
    p_report.add_argument("--ref-year", type=int, default=None)
    p_report.add_argument("--model", default=None)
    p_report.add_argument("--plan", default="full",
                          choices=["demo", "base", "extended", "full"],
                          help="Пакет доступа: demo | base | extended | full")
    p_report.add_argument("--reference", default=None,
                          help="JSON с готовыми блоками (без вызова LLM, только рендеринг HTML)")

    args = parser.parse_args()

    if args.command == "analyze":
        cmd_analyze(args)
    elif args.command == "palm":
        cmd_palm(args)
    elif args.command == "report":
        cmd_report(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()