import json
import os
import tempfile
from typing import Optional

from config import get_data_dir

HOST_SOCKET_FILENAME = "codex_tui_host.sock"
HOST_STATUS_FILENAME = "codex_tui_host_status.json"


def _resolve_data_dir(data_dir: Optional[str] = None) -> Optional[str]:
    return data_dir if data_dir is not None else get_data_dir()


def host_socket_path(data_dir: Optional[str] = None) -> Optional[str]:
    resolved = _resolve_data_dir(data_dir)
    if not resolved:
        return None
    return os.path.join(resolved, HOST_SOCKET_FILENAME)


def host_status_path(data_dir: Optional[str] = None) -> Optional[str]:
    resolved = _resolve_data_dir(data_dir)
    if not resolved:
        return None
    return os.path.join(resolved, HOST_STATUS_FILENAME)


def build_send_message_request(*, thread_id: str, text: str, topic_id: Optional[int] = None) -> dict:
    payload = {
        "type": "send_message",
        "thread_id": thread_id,
        "text": text,
    }
    if topic_id is not None:
        payload["topic_id"] = topic_id
    return payload


def encode_host_request(payload: dict) -> bytes:
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")


def decode_host_response(raw: bytes) -> dict:
    text = raw.decode("utf-8").strip()
    if not text:
        return {}
    return json.loads(text)


def read_host_status(data_dir: Optional[str] = None) -> Optional[dict]:
    path = host_status_path(data_dir)
    if not path or not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def clear_stale_host_artifacts(data_dir: Optional[str] = None) -> bool:
    socket_path = host_socket_path(data_dir)
    status_path_value = host_status_path(data_dir)
    status = read_host_status(data_dir)

    pid = status.get("pid") if isinstance(status, dict) else None
    host_online = bool(status.get("online")) if isinstance(status, dict) else False
    host_alive = False
    if isinstance(pid, int) and pid > 0:
        try:
            os.kill(pid, 0)
            host_alive = True
        except OSError:
            host_alive = False

    if host_online and host_alive and socket_path and os.path.exists(socket_path):
        return False

    changed = False
    for path in (socket_path, status_path_value):
        if not path or not os.path.exists(path):
            continue
        try:
            os.remove(path)
            changed = True
        except OSError:
            continue
    return changed


def write_host_status(payload: dict, *, data_dir: Optional[str] = None) -> None:
    path = host_status_path(data_dir)
    if not path:
        raise RuntimeError("缺少 data_dir，无法写入 codex TUI host 状态")

    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(prefix="codex-tui-host-", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise
