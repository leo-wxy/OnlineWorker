#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import sys
import tempfile


CONNECT_TIMEOUT_SECONDS = 0.12
SEND_TIMEOUT_SECONDS = 0.12


def _socket_path(data_dir: str | None) -> str:
    if not data_dir:
        return ""
    normalized = os.path.abspath(data_dir)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    socket_dir = "/tmp" if os.path.isdir("/tmp") else tempfile.gettempdir()
    return os.path.join(socket_dir, f"ow-claude-{digest}.sock")


def _read_payload() -> bytes:
    return sys.stdin.buffer.read(1024 * 1024)


def _send_fire_and_forget(socket_path: str, raw: bytes) -> None:
    if not socket_path or not raw:
        return
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(CONNECT_TIMEOUT_SECONDS)
            client.connect(socket_path)
            client.settimeout(SEND_TIMEOUT_SECONDS)
            client.sendall(raw)
            try:
                client.shutdown(socket.SHUT_WR)
            except OSError:
                pass
    except Exception:
        return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OnlineWorker Claude hook relay")
    parser.add_argument("--data-dir", default="")
    args = parser.parse_args(argv)

    raw = _read_payload()
    _send_fire_and_forget(_socket_path(args.data_dir), raw)
    sys.stdout.write("{}")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
