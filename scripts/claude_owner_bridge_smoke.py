#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
import uuid
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from cleanup_smoke_sessions import cleanup_smoke_session


DEFAULT_DATA_DIR = Path.home() / "Library/Application Support/OnlineWorker"
DEFAULT_SOCKET = DEFAULT_DATA_DIR / "provider_owner_bridge.sock"


def _request(socket_path: Path, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(timeout)
        client.connect(str(socket_path))
        client.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        chunks: list[bytes] = []
        while True:
            chunk = client.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    raw = b"".join(chunks).decode("utf-8", errors="replace").strip()
    if not raw:
        raise RuntimeError("empty provider owner bridge response")
    response = json.loads(raw)
    if not isinstance(response, dict):
        raise RuntimeError(f"invalid provider owner bridge response: {raw}")
    return response


def _contains_assistant_marker(session: list[dict[str, Any]], marker: str) -> bool:
    for turn in session:
        if not isinstance(turn, dict):
            continue
        if str(turn.get("role") or "") != "assistant":
            continue
        content = str(turn.get("content") or "")
        if marker in content:
            return True
    return False


def run_smoke(args: argparse.Namespace) -> dict[str, Any]:
    socket_path = Path(args.socket).expanduser()
    workspace = os.path.abspath(os.path.expanduser(args.workspace))
    session_id = str(uuid.uuid4())
    marker = f"{args.marker_prefix}{session_id.split('-', 1)[0]}"
    text = f"Reply exactly: {marker}"
    cleanup_preview = "onlineworker claude owner bridge smoke"
    cleanup_result: dict[str, Any] | None = None
    smoke_error: Exception | None = None

    try:
        send_payload = {
            "type": "send_message",
            "provider_id": args.provider,
            "thread_id": session_id,
            "workspace_dir": workspace,
            "text": text,
        }
        send_response = _request(socket_path, send_payload, args.timeout)
        if send_response.get("ok") is not True:
            raise RuntimeError(f"send_message failed: {json.dumps(send_response, ensure_ascii=False)}")

        deadline = time.monotonic() + args.read_timeout
        last_read: dict[str, Any] | None = None
        while True:
            read_payload = {
                "type": "read_session",
                "provider_id": args.provider,
                "session_id": session_id,
                "limit": 10,
            }
            last_read = _request(socket_path, read_payload, min(args.timeout, 20))
            if last_read.get("ok") is True and _contains_assistant_marker(
                list(last_read.get("session") or []),
                marker,
            ):
                result = {
                    "ok": True,
                    "provider_id": args.provider,
                    "thread_id": session_id,
                    "workspace": workspace,
                    "marker": marker,
                    "send_response": send_response,
                    "read_response": last_read,
                }
                break
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "assistant marker not found: "
                    + json.dumps(
                        {
                            "thread_id": session_id,
                            "marker": marker,
                            "send_response": send_response,
                            "last_read_response": last_read,
                        },
                        ensure_ascii=False,
                    )
                )
            time.sleep(args.poll_interval)
    except Exception as exc:
        smoke_error = exc
        result = None
    cleanup_error: Exception | None = None
    try:
        cleanup_result = cleanup_smoke_session(
            provider_id=args.provider,
            session_id=session_id,
            workspace_dir=workspace,
            preview=cleanup_preview,
            data_dir=DEFAULT_DATA_DIR,
            socket_path=socket_path,
            prefer_real_archive=True,
        )
    except Exception as exc:
        cleanup_error = exc

    if smoke_error is not None and cleanup_error is not None:
        raise RuntimeError(f"{smoke_error}; smoke cleanup failed: {cleanup_error}") from smoke_error
    if smoke_error is not None:
        raise smoke_error
    if cleanup_error is not None:
        raise RuntimeError(f"smoke cleanup failed: {cleanup_error}") from cleanup_error

    assert result is not None
    result["cleanup"] = cleanup_result
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Smoke-test the running OnlineWorker provider owner bridge with Claude."
    )
    parser.add_argument("--socket", default=str(DEFAULT_SOCKET))
    parser.add_argument("--provider", default="claude")
    parser.add_argument("--workspace", default=str(Path.home()))
    parser.add_argument("--marker-prefix", default="OW_CLAUDE_OWNER_SMOKE_")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--read-timeout", type=float, default=30.0)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    result = run_smoke(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
