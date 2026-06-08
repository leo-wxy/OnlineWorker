#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket
from pathlib import Path
from typing import Any


DEFAULT_DATA_DIR = Path.home() / "Library/Application Support/OnlineWorker"
STATE_FILE_NAME = "onlineworker_state.json"
SOCKET_FILE_NAME = "provider_owner_bridge.sock"


def _workspace_key(provider_id: str, workspace_dir: str) -> str:
    return f"{provider_id}:{workspace_dir}"


def _workspace_name(workspace_dir: str) -> str:
    path = Path(workspace_dir)
    return path.name or workspace_dir


def _state_path(data_dir: Path) -> Path:
    return data_dir / STATE_FILE_NAME


def _socket_path(data_dir: Path) -> Path:
    return data_dir / SOCKET_FILE_NAME


def persist_local_archived_state(
    data_dir: Path,
    provider_id: str,
    session_id: str,
    workspace_dir: str,
    preview: str | None = None,
) -> Path:
    data_dir = Path(data_dir).expanduser()
    state_path = _state_path(data_dir)

    if state_path.exists():
        raw = json.loads(state_path.read_text(encoding="utf-8"))
        state = raw if isinstance(raw, dict) else {}
    else:
        state = {}

    workspaces = state.setdefault("workspaces", {})
    if not isinstance(workspaces, dict):
        workspaces = {}
        state["workspaces"] = workspaces

    workspace_key = _workspace_key(provider_id, workspace_dir)
    workspace = workspaces.setdefault(
        workspace_key,
        {
            "name": _workspace_name(workspace_dir),
            "path": workspace_dir,
            "tool": provider_id,
            "topic_id": None,
            "daemon_workspace_id": workspace_key,
            "threads": {},
        },
    )
    if not isinstance(workspace, dict):
        workspace = {}
        workspaces[workspace_key] = workspace

    workspace.setdefault("name", _workspace_name(workspace_dir))
    workspace.setdefault("path", workspace_dir)
    workspace.setdefault("tool", provider_id)
    workspace.setdefault("daemon_workspace_id", workspace_key)
    threads = workspace.setdefault("threads", {})
    if not isinstance(threads, dict):
        threads = {}
        workspace["threads"] = threads

    thread = threads.setdefault(
        session_id,
        {
            "thread_id": session_id,
            "topic_id": None,
            "preview": None,
            "archived": False,
            "streaming_msg_id": None,
            "last_tg_user_message_id": None,
            "history_sync_cursor": None,
            "is_active": False,
            "source": "app",
        },
    )
    if not isinstance(thread, dict):
        thread = {}
        threads[session_id] = thread

    thread["thread_id"] = session_id
    thread["archived"] = True
    thread["is_active"] = False
    thread.setdefault("source", "app")
    if preview and preview.strip():
        thread["preview"] = preview.strip()

    data_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = state_path.with_suffix(".json.tmp")
    tmp_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(state_path)
    return state_path


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
    preview: str | None = None,
    data_dir: Path | str = DEFAULT_DATA_DIR,
    socket_path: Path | str | None = None,
    prefer_real_archive: bool = True,
    owner_bridge_timeout: float = 10.0,
) -> dict[str, Any]:
    provider_id = str(provider_id or "").strip()
    session_id = str(session_id or "").strip()
    workspace_dir = str(workspace_dir or "").strip()
    preview = (preview or "").strip() or None
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

    fallback_reason = ""
    if prefer_real_archive and resolved_socket_path.exists():
        try:
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
        except Exception as exc:
            fallback_reason = str(exc)

    state_path = persist_local_archived_state(
        resolved_data_dir,
        provider_id,
        session_id,
        workspace_dir,
        preview,
    )
    result = {
        "ok": True,
        "strategy": "local-overlay",
        "provider_id": provider_id,
        "session_id": session_id,
        "workspace_dir": workspace_dir,
        "state_path": str(state_path),
    }
    if fallback_reason:
        result["fallback_reason"] = fallback_reason
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Archive or locally hide smoke-test sessions.")
    parser.add_argument("--provider", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--preview", default="")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--socket", default="")
    parser.add_argument("--local-only", action="store_true")
    parser.add_argument("--timeout", type=float, default=10.0)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = cleanup_smoke_session(
        provider_id=args.provider,
        session_id=args.session_id,
        workspace_dir=args.workspace,
        preview=args.preview,
        data_dir=Path(args.data_dir),
        socket_path=Path(args.socket).expanduser() if args.socket else None,
        prefer_real_archive=not args.local_only,
        owner_bridge_timeout=float(args.timeout),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
