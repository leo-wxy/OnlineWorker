from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


CHECKED_FILES = [
    ROOT / "bot" / "handlers" / "common.py",
    ROOT / "bot" / "handlers" / "thread.py",
    ROOT / "bot" / "handlers" / "workspace.py",
    ROOT / "bot" / "handlers" / "message.py",
    ROOT / "core" / "provider_owner_bridge.py",
    ROOT / "plugins" / "providers" / "builtin" / "codex" / "python" / "runtime.py",
]


ALLOWED_TOPIC_ATTR_READS = {
    ("bot/handlers/message.py", 225),  # rollback snapshot only
}


ALLOWED_GETATTR_TOPIC_READS = {
    ("core/provider_owner_bridge.py", 1512),  # rollback snapshot only
}


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def test_tg_business_code_does_not_read_legacy_json_topic_mirrors_directly():
    violations: list[str] = []

    for path in CHECKED_FILES:
        rel = _relative(path)
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines()
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "topic_id":
                if not isinstance(node.ctx, ast.Load):
                    continue
                key = (rel, node.lineno)
                if key in ALLOWED_TOPIC_ATTR_READS:
                    continue
                line = lines[node.lineno - 1].strip()
                if "watch_state" in line or "watch." in line or "st.topic_id" in line:
                    continue
                violations.append(f"{rel}:{node.lineno}: {line}")
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "getattr"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value == "topic_id"
            ):
                key = (rel, node.lineno)
                if key in ALLOWED_GETATTR_TOPIC_READS:
                    continue
                line = lines[node.lineno - 1].strip()
                if "watch_state" in line:
                    continue
                violations.append(f"{rel}:{node.lineno}: {line}")

    assert violations == []
