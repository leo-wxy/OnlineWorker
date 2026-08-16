from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

from core.usage.contracts import UsageSummaryRequest


def resolve_ccusage_binary() -> Path:
    override = str(os.environ.get("ONLINEWORKER_CCUSAGE_BIN") or "").strip()
    candidates = [Path(override)] if override else []
    repo_root = Path(__file__).resolve().parents[5]
    candidates.extend([
        Path(sys.executable).resolve().with_name("ccusage"),
        repo_root / "third_party" / "ccusage" / "rust" / "target" / "release" / "ccusage",
    ])
    candidates.extend(sorted((repo_root / "mac-app" / "src-tauri" / "binaries").glob("ccusage-*")))
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise FileNotFoundError("Bundled ccusage sidecar is unavailable")


def runtime_identity() -> str:
    binary = resolve_ccusage_binary()
    stat = binary.stat()
    return f"{binary}:{stat.st_mtime_ns}:{stat.st_size}"


def _source_data_roots(source_id: str) -> list[Path]:
    home = Path.home()
    if source_id == "codex":
        raw_homes = str(os.environ.get("CODEX_HOME") or "").strip()
        homes = [Path(value.strip()) for value in raw_homes.split(",") if value.strip()]
        if not homes:
            homes = [home / ".codex"]
        roots = []
        for codex_home in homes:
            session_roots = [
                path for path in (
                    codex_home / "sessions",
                    codex_home / "archived_sessions",
                )
                if path.is_dir()
            ]
            roots.extend(session_roots or [codex_home])
        return roots

    if source_id == "claude":
        raw_homes = str(os.environ.get("CLAUDE_CONFIG_DIR") or "").strip()
        if raw_homes:
            homes = [Path(value.strip()).expanduser() for value in raw_homes.split(",") if value.strip()]
        else:
            xdg_home = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
            homes = [xdg_home / "claude", home / ".claude"]
        return [
            path if path.name == "projects" else path / "projects"
            for path in homes
            if (path if path.name == "projects" else path / "projects").is_dir()
        ]

    return []


def _source_data_identity(source_id: str) -> str | None:
    roots = _source_data_roots(source_id)
    if not roots:
        return None
    digest = hashlib.blake2b(digest_size=16)
    for root in roots:
        digest.update(os.fsencode(root))
        try:
            paths = sorted(root.rglob("*.jsonl"))
        except OSError:
            continue
        for path in paths:
            try:
                file_stat = path.stat()
            except OSError:
                continue
            digest.update(os.fsencode(path))
            digest.update(
                f":{file_stat.st_ino}:{file_stat.st_mtime_ns}:{file_stat.st_size}".encode()
            )
    return digest.hexdigest()


def _integer(row: dict[str, Any], key: str) -> int:
    try:
        return max(0, int(row.get(key) or 0))
    except (TypeError, ValueError):
        return 0


def _cost(row: dict[str, Any]) -> float | None:
    value = row.get("totalCost", row.get("costUSD"))
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _run_ccusage_summary(request: UsageSummaryRequest) -> dict[str, Any]:
    binary = resolve_ccusage_binary()
    args = [
        str(binary), request.source_id, "daily", "--json", "--no-cost", "--offline",
        "--since", request.start_date, "--until", request.end_date,
    ]
    if request.timezone and request.timezone != "local":
        args.extend(["--timezone", request.timezone])
    completed = subprocess.run(args, capture_output=True, text=True, timeout=30, check=False)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or f"exit {completed.returncode}"
        raise RuntimeError(f"ccusage failed: {detail}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"ccusage returned invalid JSON: {exc}") from exc
    rows = payload.get("daily") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        rows = []
    days = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        date = str(raw.get("date") or raw.get("period") or "").strip()
        if not date:
            continue
        days.append({
            "date": date,
            "inputTokens": _integer(raw, "inputTokens"),
            "outputTokens": _integer(raw, "outputTokens"),
            "cacheCreationTokens": _integer(raw, "cacheCreationTokens"),
            "cacheReadTokens": _integer(raw, "cacheReadTokens"),
            "totalTokens": _integer(raw, "totalTokens"),
            "totalCostUsd": _cost(raw),
        })
    days.sort(key=lambda item: item["date"], reverse=True)
    return {"days": days, "updatedAtEpoch": int(time.time())}


@lru_cache(maxsize=32)
def _cached_ccusage_summary(
    request: UsageSummaryRequest,
    _binary_identity: str,
    _data_identity: str,
) -> dict[str, Any]:
    return _run_ccusage_summary(request)


def run_ccusage_summary(request: UsageSummaryRequest) -> dict[str, Any]:
    data_identity = _source_data_identity(request.source_id)
    if data_identity is None:
        return _run_ccusage_summary(request)
    summary = deepcopy(_cached_ccusage_summary(request, runtime_identity(), data_identity))
    summary["updatedAtEpoch"] = int(time.time())
    return summary
