import os
import socket
import stat
from urllib.parse import urlparse


DEFAULT_CODEX_UNIX_SOCKET = os.path.join(
    "app-server-control",
    "app-server-control.sock",
)
ONLINEWORKER_CODEX_UNIX_SOCKET = os.path.join(
    "app-server-control",
    "onlineworker-app-server.sock",
)


def is_unix_endpoint(url: str) -> bool:
    return str(url or "").strip().lower().startswith("unix://")


def is_default_unix_endpoint(url: str) -> bool:
    return str(url or "").strip().lower() in {"", "unix://"}


def default_codex_home() -> str:
    return os.path.expanduser(os.environ.get("CODEX_HOME") or "~/.codex")


def onlineworker_codex_unix_url() -> str:
    """Return the dedicated Unix endpoint owned by OnlineWorker."""
    path = os.path.join(default_codex_home(), ONLINEWORKER_CODEX_UNIX_SOCKET)
    return f"unix://{path}"


def resolve_unix_socket_path(url: str) -> str:
    """Resolve Codex app-server unix:// endpoint to a filesystem socket path."""
    value = str(url or "").strip()
    if value in {"", "unix://"}:
        return os.path.join(default_codex_home(), DEFAULT_CODEX_UNIX_SOCKET)

    parsed = urlparse(value)
    if parsed.scheme != "unix":
        raise ValueError(f"unsupported unix app-server endpoint: {url}")

    path = parsed.path or ""
    if not path and parsed.netloc:
        path = parsed.netloc
    elif parsed.netloc and path:
        path = f"{parsed.netloc}{path}"

    if not path:
        return os.path.join(default_codex_home(), DEFAULT_CODEX_UNIX_SOCKET)
    return os.path.abspath(os.path.expanduser(path))


def _unix_socket_accepting(path: str, timeout: float = 0.1) -> bool:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(path)
        return True
    except OSError:
        return False
    finally:
        sock.close()


def unix_socket_accepting(url: str, timeout: float = 0.1) -> bool:
    try:
        path = resolve_unix_socket_path(url)
    except ValueError:
        return False
    try:
        mode = os.stat(path).st_mode
    except FileNotFoundError:
        return False
    if not stat.S_ISSOCK(mode):
        return False
    return _unix_socket_accepting(path, timeout=timeout)


def prepare_unix_socket_path(url: str) -> str:
    """Create parent dir and remove a stale socket file before starting app-server."""
    path = resolve_unix_socket_path(url)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    try:
        mode = os.stat(path).st_mode
    except FileNotFoundError:
        return path

    if stat.S_ISSOCK(mode) and not _unix_socket_accepting(path):
        os.unlink(path)
        return path

    return path
