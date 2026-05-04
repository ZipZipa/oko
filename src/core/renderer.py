"""
Общий рендерер Jinja2 — используется всеми типами отчётов.
"""
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape


def render_template(templates_dir: Path, template_name: str,
                    data: dict, blocks: dict) -> str:
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template(template_name)
    return template.render(data=data, blocks=blocks)
