from __future__ import annotations

import sys


def run_codex_hook_bridge_once() -> int:
    try:
        sys.stdin.buffer.read()
    except Exception:
        pass
    sys.stdout.write("{}")
    sys.stdout.flush()
    return 0
