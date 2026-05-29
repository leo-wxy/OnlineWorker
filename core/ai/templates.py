from __future__ import annotations

import re
from typing import Any

_TEMPLATE_VAR_PATTERN = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


def render_prompt_template(template: str, variables: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        value = variables.get(key, "")
        return "" if value is None else str(value)

    return _TEMPLATE_VAR_PATTERN.sub(replace, str(template or ""))
