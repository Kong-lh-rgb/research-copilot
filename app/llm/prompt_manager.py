"""Jinja2-based prompt template manager.

Templates live in  app/prompts/templates/*.jinja  and are resolved relative to
the project root so the manager works regardless of where Python is invoked.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateNotFound

logger = logging.getLogger(__name__)

# Resolve the templates directory relative to *this* file so it works from any
# working directory (e.g. `python -m app.main` from repo root).
_TEMPLATES_DIR = Path(__file__).parent.parent / "prompts" / "templates"

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    undefined=StrictUndefined,   # raise on missing variables → catch bugs early
    keep_trailing_newline=True,
    trim_blocks=False,
    lstrip_blocks=False,
)


def render(template_name: str, **kwargs: Any) -> str:
    """Render a Jinja2 template by name (without the .jinja extension).

    Example::

        system = render("worker",
                        conversation_history=history,
                        user_input=query,
                        dependencies_context=deps,
                        task_id=task_id,
                        task_description=task.description)
    """
    filename = f"{template_name}.jinja"
    try:
        template = _env.get_template(filename)
    except TemplateNotFound:
        raise FileNotFoundError(
            f"[PromptManager] 模板文件不存在: {_TEMPLATES_DIR / filename}"
        )
    rendered = template.render(**kwargs)
    logger.debug("[PromptManager] 渲染模板 '%s'（%d 字符）", template_name, len(rendered))
    return rendered
