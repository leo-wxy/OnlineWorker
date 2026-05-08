from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from uuid import UUID
from types import SimpleNamespace


def _load_smoke_module():
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "scripts" / "provider_smoke.py"
    spec = importlib.util.spec_from_file_location("provider_smoke", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_extract_thread_id_accepts_public_shapes():
    module = _load_smoke_module()

    assert module.extract_thread_id({"id": "tid-direct"}) == "tid-direct"
    assert module.extract_thread_id({"thread": {"id": "tid-nested"}}) == "tid-nested"
    assert module.extract_thread_id({}) == ""


def test_fixed_claude_session_id_is_deterministic():
    module = _load_smoke_module()

    first = module.default_fixed_session_id("claude")
    second = module.default_fixed_session_id("claude")

    assert first == second
    assert str(UUID(first)) == first


def test_provider_permission_reply_formats_are_stable():
    module = _load_smoke_module()

    assert module.build_permission_reply("codex", "tid-1") == {"decision": "accept"}
    assert module.build_permission_reply("codex", "tid-1", "execCommandApproval") == {
        "decision": "approved",
    }
    assert module.build_permission_reply("claude", "tid-1") == {"behavior": "allow"}
    try:
        module.build_permission_reply("unknown", "tid-1")
    except ValueError as exc:
        assert "unknown provider" in str(exc)
    else:
        raise AssertionError("unknown provider should be rejected")


def test_codex_permission_turn_requests_untrusted_approval_policy():
    module = _load_smoke_module()

    assert module._permission_send_kwargs("codex") == {
        "approval_policy": "untrusted",
        "approvals_reviewer": "user",
        "sandbox_policy": {"type": "readOnly"},
    }
    assert module._permission_send_kwargs("claude") == {}


def test_connect_adapter_auto_starts_local_codex_server_on_refused_connection(monkeypatch):
    module = _load_smoke_module()

    calls: list[tuple[str, object | None]] = []

    class FakeCodexAdapter:
        def __init__(self):
            self.connected_urls: list[str] = []
            self._first_connect = True

        async def connect(self, url: str, process=None):
            calls.append((url, process))
            self.connected_urls.append(url)
            if self._first_connect and url == "ws://127.0.0.1:4722" and process is None:
                self._first_connect = False
                raise ConnectionRefusedError("refused")
            self._first_connect = False

    class FakeAppServerProcess:
        def __init__(self, codex_bin: str, port: int, protocol: str):
            self.codex_bin = codex_bin
            self.port = port
            self.protocol = protocol
            self.started = False
            self.stopped = False

        async def start(self):
            self.started = True
            return "ws://127.0.0.1:4722"

        async def stop(self):
            self.stopped = True

    monkeypatch.setattr("plugins.providers.builtin.codex.python.adapter.CodexAdapter", FakeCodexAdapter)
    monkeypatch.setattr("plugins.providers.builtin.codex.python.process.AppServerProcess", FakeAppServerProcess)

    args = SimpleNamespace(
        codex_url="ws://127.0.0.1:4722",
        codex_bin="codex",
        smoke_dir=Path("/tmp/onlineworker-smoke"),
    )

    adapter, app_server = asyncio.run(module._connect_adapter("codex", args))

    assert isinstance(adapter, FakeCodexAdapter)
    assert isinstance(app_server, FakeAppServerProcess)
    assert app_server.started is True
    assert app_server.stopped is False
    assert calls == [
        ("ws://127.0.0.1:4722", None),
        ("ws://127.0.0.1:4722", None),
    ]


def test_permission_prompt_uses_repo_local_target():
    module = _load_smoke_module()
    target = Path("/repo/.onlineworker-smoke/artifacts/codex-permission.txt")

    prompt = module.build_permission_prompt("codex", target, "content")

    assert str(target) in prompt
    assert "python3 -c" in prompt
    assert "ONLINEWORKER_SMOKE_PERMISSION_OK" in prompt


def test_session_store_reuses_existing_provider_thread(tmp_path):
    module = _load_smoke_module()
    store = module.SmokeSessionStore(tmp_path / "state.json")

    store.set_thread_id("codex", "tid-fixed")

    assert store.get_thread_id("codex") == "tid-fixed"
    assert module.SmokeSessionStore(tmp_path / "state.json").get_thread_id("codex") == "tid-fixed"
