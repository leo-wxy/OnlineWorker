from __future__ import annotations

import json
import os
import subprocess
import sys
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


def run_ccusage_summary(request: UsageSummaryRequest) -> dict[str, Any]:
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
    return {"days": days, "updatedAtEpoch": int(__import__("time").time())}
