#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket
from pathlib import Path
from typing import Any


DEFAULT_DATA_DIR = Path.home() / "Library/Application Support/OnlineWorker"
SOCKET_FILE_NAME = "provider_owner_bridge.sock"


def _socket_path(data_dir: Path) -> Path:
    return data_dir / SOCKET_FILE_NAME


def request_owner_bridge_archive(
    socket_path: Path,
    provider_id: str,
    session_id: str,
    workspace_dir: str,
    *,
    timeout: float = 10.0,
) -> dict[str, Any]:
    payload = {
        "type": "archive_session",
        "provider_id": provider_id,
        "session_id": session_id,
        "workspace_dir": workspace_dir,
    }
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        client.connect(str(socket_path))
        client.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        client.shutdown(socket.SHUT_WR)
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
    if response.get("ok") is not True:
        raise RuntimeError(str(response.get("error") or "provider owner bridge archive failed"))
    return response


def cleanup_smoke_session(
    *,
    provider_id: str,
    session_id: str,
    workspace_dir: str,
    data_dir: Path | str = DEFAULT_DATA_DIR,
    socket_path: Path | str | None = None,
    owner_bridge_timeout: float = 10.0,
) -> dict[str, Any]:
    provider_id = str(provider_id or "").strip()
    session_id = str(session_id or "").strip()
    workspace_dir = str(workspace_dir or "").strip()
    if not provider_id:
        raise ValueError("provider_id is required")
    if not session_id:
        raise ValueError("session_id is required")
    if not workspace_dir:
        raise ValueError("workspace_dir is required")

    resolved_data_dir = Path(data_dir).expanduser()
    resolved_socket_path = (
        Path(socket_path).expanduser()
        if socket_path is not None
        else _socket_path(resolved_data_dir)
    )

    if not resolved_socket_path.exists():
        raise RuntimeError(f"provider owner bridge socket not found: {resolved_socket_path}")

    response = request_owner_bridge_archive(
        resolved_socket_path,
        provider_id,
        session_id,
        workspace_dir,
        timeout=owner_bridge_timeout,
    )
    return {
        "ok": True,
        "strategy": "real-archive",
        "provider_id": provider_id,
        "session_id": session_id,
        "workspace_dir": workspace_dir,
        "response": response,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Archive smoke-test sessions through provider owner bridge.")
    parser.add_argument("--provider", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--socket", default="")
    parser.add_argument("--timeout", type=float, default=10.0)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = cleanup_smoke_session(
        provider_id=args.provider,
        session_id=args.session_id,
        workspace_dir=args.workspace,
        data_dir=Path(args.data_dir),
        socket_path=Path(args.socket).expanduser() if args.socket else None,
        owner_bridge_timeout=float(args.timeout),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
