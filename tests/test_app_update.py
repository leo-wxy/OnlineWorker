import asyncio
import base64
import importlib.util
import json
from pathlib import Path
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.messages.events import create_message_event
from core.provider_owner_bridge import ProviderOwnerBridge
from core.provider_session_new import start_real_provider_thread
from core.state import AppState
from core.storage import AppStorage
from plugins.providers.builtin.codex.python.remote_proxy import CodexRemoteMessageProxy, _ProxyConnectionContext

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("updater_manifest", ROOT / "scripts/create-updater-manifest.py")
manifest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manifest)


def signing_packet(size, key_id=b"sampleid"):
    packet = b"Ed" + key_id + b"\x00" * (size - 10)
    return base64.b64encode(("untrusted comment: synthetic fixture\n" + base64.b64encode(packet).decode() + "\n").encode()).decode()


def test_mac_build_keeps_app_and_generates_updater_artifacts():
    config = json.loads((ROOT / "mac-app/src-tauri/tauri.conf.json").read_text())
    assert {"app", "dmg"} <= set(config["bundle"]["targets"])
    assert config["bundle"]["createUpdaterArtifacts"] is True


def test_manifest_requires_two_architectures_and_matching_app_signing_key(tmp_path):
    public = signing_packet(42)
    for arch in ["arm64", "x86_64"]:
        package = tmp_path / f"OnlineWorker_9.8.7_{arch}.app.tar.gz"
        package.write_bytes(b"synthetic updater package")
        package.with_suffix(package.suffix + ".sig").write_text(signing_packet(74))
    result = manifest.build_manifest("9.8.7", "v9.8.7", "example/sample", tmp_path, public)
    assert set(result["platforms"]) == {"darwin-aarch64", "darwin-x86_64"}
    assert result["platforms"]["darwin-aarch64"]["url"].endswith("/OnlineWorker_9.8.7_arm64.app.tar.gz")
    assert result["platforms"]["darwin-x86_64"]["signature"] == signing_packet(74)
    with pytest.raises(ValueError, match="VERSION"):
        manifest.build_manifest("9.8.7", "9.8.8", "example/sample", tmp_path, public)
    bad_signature = tmp_path / "OnlineWorker_9.8.7_x86_64.app.tar.gz.sig"
    bad_signature.write_text(signing_packet(74, b"otherkey"))
    with pytest.raises(ValueError, match="public key"):
        manifest.build_manifest("9.8.7", "9.8.7", "example/sample", tmp_path, public)
    bad_signature.unlink()
    with pytest.raises(ValueError, match="Missing"):
        manifest.build_manifest("9.8.7", "9.8.7", "example/sample", tmp_path, public)


@pytest.mark.asyncio
async def test_update_admission_blocks_new_app_and_telegram_tasks_and_expires(tmp_path):
    state = AppState(storage=AppStorage())
    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    with state.task_admission():
        assert not bridge._handle_prepare_app_update()["ok"]
    assert bridge._handle_prepare_app_update() == {"ok": True}
    for handle in (bridge._handle_send_message, bridge._handle_start_session_message, bridge._handle_create_session):
        result = await handle({})
        assert not result["ok"] and "正在准备更新" in result["error"]
    from bot.handlers.message import _dispatch_thread_message
    with pytest.raises(RuntimeError, match="正在准备更新"):
        await _dispatch_thread_message(state, None, None)
    adapter = SimpleNamespace(start_thread=AsyncMock())
    with pytest.raises(RuntimeError, match="正在准备更新"):
        await start_real_provider_thread(adapter, None, "sample-workspace", state=state)
    adapter.start_thread.assert_not_awaited()
    state.app_update_deadline = time.monotonic() - 1
    with state.task_admission():
        assert state.active_task_dispatches == 1
    assert state.active_task_dispatches == 0


def test_update_admission_ignores_failed_send_timing_and_rechecks_renewal(tmp_path):
    state = AppState()
    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    state.mark_provider_send_started("codex", "sample-session")
    state.message_bus.publish(create_message_event("message.user.send_failed", provider_id="codex",
        session_id="sample-session", payload={"deliveryStatus": "failed", "error": "rejected"}))
    assert bridge._handle_prepare_app_update()["ok"]
    deadline = state.app_update_deadline
    assert bridge._handle_prepare_app_update()["ok"]
    assert state.app_update_deadline >= deadline
    state.message_bus.publish(create_message_event("turn.started", provider_id="codex", session_id="sample-session"))
    assert not bridge._handle_prepare_app_update()["ok"]


@pytest.mark.asyncio
async def test_remote_cli_connection_blocks_update_and_releases_on_failure(monkeypatch, tmp_path):
    state = AppState()
    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    proxy = CodexRemoteMessageProxy(state=state, upstream_url="unix:///tmp/sample-upstream.sock",
                                   listen_url="unix:///tmp/sample-proxy.sock")
    entered, close = asyncio.Event(), asyncio.Event()
    async def relay(_):
        entered.set()
        await close.wait()
        raise ConnectionError("synthetic upstream failure")
    monkeypatch.setattr(proxy, "_handle_admitted_client", relay)
    task = asyncio.create_task(proxy._handle_client(SimpleNamespace()))
    await entered.wait()
    assert not bridge._handle_prepare_app_update()["ok"]
    close.set()
    with pytest.raises(ConnectionError):
        await task
    assert state.active_task_dispatches == 0
    assert bridge._handle_prepare_app_update()["ok"]


@pytest.mark.asyncio
async def test_proxy_send_failure_and_steer_error_never_change_turn_state():
    state = AppState()
    proxy = CodexRemoteMessageProxy(state=state, upstream_url="unix:///tmp/sample-upstream.sock",
                                   listen_url="unix:///tmp/sample-proxy.sock")
    context = _ProxyConnectionContext(connection_id="sample-connection")
    class Frames:
        def __init__(self, *messages):
            self.messages = iter(messages)
            self.send = AsyncMock()
        def __aiter__(self):
            return self
        async def __anext__(self):
            try:
                return json.dumps(next(self.messages))
            except StopIteration:
                raise StopAsyncIteration
    upstream = Frames()
    upstream.send.side_effect = ConnectionError("synthetic upstream failure")
    with pytest.raises(ConnectionError):
        await proxy._relay_client_to_upstream(Frames({"id": 1, "method": "turn/start", "params": {
            "threadId": "sample-session", "input": []}}), upstream, context)
    assert not state.get_provider_runtime("codex").active_threads
    state.mark_provider_tui_turn_started("codex", "sample-session")
    upstream.send.side_effect = None
    await proxy._relay_client_to_upstream(Frames({"id": 2, "method": "turn/steer", "params": {
        "threadId": "sample-session", "input": []}}), upstream, context)
    await proxy._relay_upstream_to_client(Frames({"id": 2, "error": {"message": "rejected"}}), Frames(), context)
    assert state.get_provider_runtime("codex").active_threads == {"sample-session"}
    assert not state.get_provider_tui_thread_idle_event("codex", "sample-session").is_set()


@pytest.mark.parametrize("kind,payload", [
    ("turn.started", {}), ("question.requested", {"questionId": "sample-question"}),
    ("message.user.submitted", {"text": "sample task"}),
    ("message.user.send_failed", {"deliveryStatus": "uncertain", "error": "response lost"}),
])
def test_running_or_unaccepted_task_cannot_enter_update_drain(tmp_path, kind, payload):
    state = AppState()
    state.message_bus.publish(create_message_event(kind, provider_id="claude", session_id="sample-session", payload=payload))
    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    assert not bridge._handle_prepare_app_update()["ok"]
    assert state.app_update_deadline == 0


@pytest.mark.asyncio
async def test_update_drain_rejects_raw_codex_image_input_before_it_reaches_upstream():
    state = AppState()
    state.app_update_deadline = time.monotonic() + 30
    frame = json.dumps({"id": 123, "method": "turn/start", "params": {
        "threadId": "sample-session", "input": [{"type": "image", "url": "https://example.test/image.png"}],
    }})
    async def frames():
        yield frame
    client = SimpleNamespace(__aiter__=lambda _: frames(), send=AsyncMock())
    class Client:
        def __aiter__(self): return frames()
        send = client.send
    upstream = SimpleNamespace(send=AsyncMock())
    proxy = CodexRemoteMessageProxy(state=state, upstream_url="unix:///tmp/sample-upstream.sock", listen_url="unix:///tmp/sample-proxy.sock")
    await proxy._relay_client_to_upstream(Client(), upstream, _ProxyConnectionContext(connection_id="sample-connection"))
    upstream.send.assert_not_awaited()
    response = json.loads(client.send.await_args.args[0])
    assert response["id"] == 123
    assert response["error"]["code"] == -32000
