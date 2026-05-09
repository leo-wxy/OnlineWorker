from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_smoke_module():
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "scripts" / "claude_hook_smoke.py"
    spec = importlib.util.spec_from_file_location("claude_hook_smoke", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_permission_smoke_plan_uses_second_run_for_allow_always():
    module = _load_smoke_module()
    target = Path("/tmp/onlineworker-claude-smoke.txt")

    plan = module.build_permission_smoke_plan(
        target=target,
        content="hello",
        allow_always=True,
    )

    assert plan["expected_approvals"] == 1
    assert [step["label"] for step in plan["runs"]] == ["first", "second"]
    assert plan["runs"][0]["target"] == target
    assert plan["runs"][1]["target"] != target
    assert plan["runs"][1]["target"].name.startswith(target.stem)
    assert plan["runs"][1]["content"] != "hello"


def test_build_permission_smoke_plan_keeps_single_run_without_allow_always():
    module = _load_smoke_module()
    target = Path("/tmp/onlineworker-claude-smoke.txt")

    plan = module.build_permission_smoke_plan(
        target=target,
        content="hello",
        allow_always=False,
    )

    assert plan == {
        "expected_approvals": 1,
        "runs": [
            {
                "label": "first",
                "target": target,
                "content": "hello",
            }
        ],
    }


def test_resolve_bridge_python_prefers_env_override(monkeypatch):
    module = _load_smoke_module()
    monkeypatch.setenv("ONLINEWORKER_BRIDGE_PYTHON", "/tmp/custom-python")

    assert module._resolve_bridge_python() == "/tmp/custom-python"


def test_resolve_bridge_python_falls_back_to_current_interpreter(monkeypatch):
    module = _load_smoke_module()
    monkeypatch.delenv("ONLINEWORKER_BRIDGE_PYTHON", raising=False)

    assert module._resolve_bridge_python() == sys.executable
