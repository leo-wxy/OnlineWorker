import json
from pathlib import Path

from plugins.providers.builtin.codex.python.tui_host_protocol import (
    build_send_message_request,
    decode_host_response,
    encode_host_request,
    host_socket_path,
    host_status_path,
    read_host_status,
    write_host_status,
)


def test_host_paths_resolve_inside_data_dir(tmp_path):
    assert host_socket_path(str(tmp_path)) == str(tmp_path / "codex_tui_host.sock")
    assert host_status_path(str(tmp_path)) == str(tmp_path / "codex_tui_host_status.json")


def test_write_and_read_host_status_round_trip(tmp_path):
    payload = {
        "online": True,
        "pid": 1234,
        "child_pid": 5678,
        "cwd": "/Users/example/Projects/onlineWorker",
        "remote_url": "ws://127.0.0.1:4722",
        "active_thread_id": "tid-1",
        "socket_path": str(tmp_path / "codex_tui_host.sock"),
        "updated_at_epoch": 1770000000.0,
    }

    write_host_status(payload, data_dir=str(tmp_path))
    loaded = read_host_status(data_dir=str(tmp_path))

    assert loaded == payload


def test_encode_and_decode_host_messages():
    request = build_send_message_request(thread_id="tid-1", text="你好", topic_id=100)
    raw = encode_host_request(request)
    assert raw.endswith(b"\n")

    response = {
        "ok": True,
        "accepted": True,
        "active_thread_id": "tid-1",
    }
    decoded = decode_host_response(json.dumps(response).encode("utf-8") + b"\n")
    assert decoded == response


def test_read_host_status_returns_none_when_missing(tmp_path):
    assert read_host_status(data_dir=str(tmp_path)) is None
