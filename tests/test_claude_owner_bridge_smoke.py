from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_smoke_module():
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "scripts" / "claude_owner_bridge_smoke.py"
    spec = importlib.util.spec_from_file_location("claude_owner_bridge_smoke", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_run_smoke_cleans_up_session(monkeypatch, tmp_path):
    module = _load_smoke_module()
    requests: list[dict] = []
    cleanup_calls: list[dict] = []

    def fake_request(_socket_path, payload, _timeout):
        requests.append(payload)
        if payload["type"] == "send_message":
            return {"ok": True}
        return {"ok": True, "session": [{"role": "assistant", "content": "marker ok"}]}

    def fake_cleanup(**kwargs):
        cleanup_calls.append(kwargs)
        return {"ok": True, "strategy": "local-overlay"}

    monkeypatch.setattr(module, "_request", fake_request)
    monkeypatch.setattr(module, "_contains_assistant_marker", lambda _session, _marker: True)
    monkeypatch.setattr(module, "cleanup_smoke_session", fake_cleanup)

    args = type(
        "Args",
        (),
        {
            "socket": str(tmp_path / "provider_owner_bridge.sock"),
            "provider": "claude",
            "workspace": str(tmp_path),
            "marker_prefix": "OW_SMOKE_",
            "timeout": 3.0,
            "read_timeout": 3.0,
            "poll_interval": 0.0,
        },
    )()

    result = module.run_smoke(args)

    assert requests[0]["type"] == "send_message"
    assert cleanup_calls
    assert cleanup_calls[0]["provider_id"] == "claude"
    assert cleanup_calls[0]["workspace_dir"] == str(tmp_path)
    assert result["cleanup"]["strategy"] == "local-overlay"


def test_run_smoke_follows_remapped_thread_for_read_and_cleanup(monkeypatch, tmp_path):
    module = _load_smoke_module()
    requested_thread_ids: list[str] = []
    read_session_ids: list[str] = []
    cleanup_calls: list[dict] = []
    remapped_thread_id = "00000000-0000-7000-8000-000000000004"

    def fake_request(_socket_path, payload, _timeout):
        if payload["type"] == "send_message":
            requested_thread_ids.append(payload["thread_id"])
            return {
                "ok": True,
                "accepted": True,
                "thread_id": remapped_thread_id,
                "requested_thread_id": payload["thread_id"],
                "remapped": True,
            }
        read_session_ids.append(payload["session_id"])
        return {"ok": True, "session": [{"role": "assistant", "content": "marker ok"}]}

    def fake_cleanup(**kwargs):
        cleanup_calls.append(kwargs)
        return {"ok": True, "strategy": "real-archive"}

    monkeypatch.setattr(module, "_request", fake_request)
    monkeypatch.setattr(module, "_contains_assistant_marker", lambda _session, _marker: True)
    monkeypatch.setattr(module, "cleanup_smoke_session", fake_cleanup)

    args = type(
        "Args",
        (),
        {
            "socket": str(tmp_path / "provider_owner_bridge.sock"),
            "provider": "codex",
            "workspace": str(tmp_path),
            "marker_prefix": "OW_CODEX_SMOKE_",
            "timeout": 3.0,
            "read_timeout": 3.0,
            "poll_interval": 0.0,
        },
    )()

    result = module.run_smoke(args)

    assert requested_thread_ids
    assert requested_thread_ids[0] != remapped_thread_id
    assert read_session_ids == [remapped_thread_id]
    assert cleanup_calls[0]["session_id"] == remapped_thread_id
    assert result["thread_id"] == remapped_thread_id
    assert result["requested_thread_id"] == requested_thread_ids[0]
