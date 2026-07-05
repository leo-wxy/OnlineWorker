from __future__ import annotations

import importlib.util
import json
import socket
import tempfile
import threading
from pathlib import Path

import pytest


def _load_cleanup_module():
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "scripts" / "cleanup_smoke_sessions.py"
    spec = importlib.util.spec_from_file_location("cleanup_smoke_sessions", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _serve_owner_bridge_once(socket_path: Path, response: dict):
    requests: list[dict] = []
    ready = threading.Event()
    done = threading.Event()
    errors: list[BaseException] = []

    def run() -> None:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
                server.bind(str(socket_path))
                server.listen(1)
                ready.set()
                conn, _ = server.accept()
                with conn:
                    chunks: list[bytes] = []
                    while True:
                        chunk = conn.recv(65536)
                        if not chunk:
                            break
                        chunks.append(chunk)
                    raw = b"".join(chunks).decode("utf-8").strip()
                    requests.append(json.loads(raw))
                    conn.sendall((json.dumps(response) + "\n").encode("utf-8"))
                done.set()
        except BaseException as exc:  # pragma: no cover - surfaced by assertions below
            errors.append(exc)
            ready.set()
            done.set()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    assert ready.wait(2)
    assert not errors
    return requests, done, errors


def test_cleanup_smoke_session_requires_owner_bridge_socket(tmp_path):
    module = _load_cleanup_module()

    with pytest.raises(RuntimeError, match="provider owner bridge socket not found"):
        module.cleanup_smoke_session(
            provider_id="claude",
            session_id="ses-smoke",
            workspace_dir="/tmp/workspace",
            data_dir=tmp_path,
            socket_path=tmp_path / "missing.sock",
        )

    assert not (tmp_path / "onlineworker_state.json").exists()


def test_cleanup_smoke_session_archives_through_owner_bridge():
    module = _load_cleanup_module()

    with tempfile.TemporaryDirectory(prefix="ows-", dir="/tmp") as raw_dir:
        data_dir = Path(raw_dir)
        socket_path = data_dir / "bridge.sock"
        requests, done, errors = _serve_owner_bridge_once(
            socket_path,
            {"ok": True, "archived": True},
        )

        result = module.cleanup_smoke_session(
            provider_id="claude",
            session_id="ses-smoke",
            workspace_dir="/tmp/workspace",
            data_dir=data_dir,
            socket_path=socket_path,
        )

        assert done.wait(2)
        assert not errors
        assert requests == [
            {
                "type": "archive_session",
                "provider_id": "claude",
                "session_id": "ses-smoke",
                "workspace_dir": "/tmp/workspace",
            }
        ]
        assert result["ok"] is True
        assert result["strategy"] == "real-archive"
        assert result["response"] == {"ok": True, "archived": True}
        assert not (data_dir / "onlineworker_state.json").exists()
