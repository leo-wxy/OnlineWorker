from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_cleanup_module():
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "scripts" / "cleanup_smoke_sessions.py"
    spec = importlib.util.spec_from_file_location("cleanup_smoke_sessions", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_persist_local_archived_state_writes_onlineworker_state(tmp_path):
    module = _load_cleanup_module()

    state_path = module.persist_local_archived_state(
        tmp_path,
        "claude",
        "ses-smoke",
        "/tmp/workspace",
        "onlineworker claude smoke",
    )

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    thread = payload["workspaces"]["claude:/tmp/workspace"]["threads"]["ses-smoke"]
    assert state_path == tmp_path / "onlineworker_state.json"
    assert thread["thread_id"] == "ses-smoke"
    assert thread["archived"] is True
    assert thread["is_active"] is False
    assert thread["preview"] == "onlineworker claude smoke"


def test_cleanup_smoke_session_falls_back_to_local_overlay_when_owner_bridge_missing(tmp_path):
    module = _load_cleanup_module()

    result = module.cleanup_smoke_session(
        provider_id="claude",
        session_id="ses-smoke",
        workspace_dir="/tmp/workspace",
        preview="onlineworker claude smoke",
        data_dir=tmp_path,
        socket_path=tmp_path / "missing.sock",
        prefer_real_archive=True,
    )

    assert result["ok"] is True
    assert result["strategy"] == "local-overlay"
    state_path = tmp_path / "onlineworker_state.json"
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["workspaces"]["claude:/tmp/workspace"]["threads"]["ses-smoke"]["archived"] is True
