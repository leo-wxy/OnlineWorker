#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import socket
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = Path.home() / "Library/Application Support/OnlineWorker"
DEFAULT_OWNER_BRIDGE_SOCKET = DEFAULT_DATA_DIR / "provider_owner_bridge.sock"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from plugins.providers.builtin.claude.python.adapter import (  # noqa: E402
    CLAUDE_ENV_VARS,
    ClaudeAdapter,
    _collect_claude_runtime_env,
    _readiness_from_runtime_env,
    resolve_claude_command_prefix,
)


SAFE_READINESS_KEYS = {
    "ready",
    "source",
    "reason",
    "authMethod",
    "checked_at",
    "detail",
    "apiProvider",
    "launchMethod",
}
SAFE_METHOD_KEYS = {
    "id",
    "label",
    "selected",
    "detected",
    "available",
    "ready",
    "reason",
    "detail",
    "command",
    "configured",
    "config_source",
    "present_env_keys",
}


def sanitize_readiness(readiness: dict[str, Any] | None) -> dict[str, Any]:
    data = readiness if isinstance(readiness, dict) else {}
    sanitized: dict[str, Any] = {}
    for key in SAFE_READINESS_KEYS:
        if key not in data:
            continue
        value = data[key]
        if value is None:
            continue
        sanitized[key] = value
    return sanitized


def sanitize_method(method: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key in SAFE_METHOD_KEYS:
        if key not in method:
            continue
        value = method[key]
        if value is None:
            continue
        sanitized[key] = value
    return sanitized


def _safe_command_display(prefix: list[str]) -> str:
    return " ".join(str(part or "").strip() for part in prefix if str(part or "").strip())


def _load_yaml(path: Path) -> dict[str, Any]:
    import yaml

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _normalize_launch_methods(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    methods: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if isinstance(item, str):
            command = item.strip()
            method_id = f"method_{index + 1}"
            label = command
        elif isinstance(item, dict):
            command = str(item.get("bin") or item.get("command") or "").strip()
            method_id = str(item.get("id") or item.get("name") or f"method_{index + 1}").strip()
            label = str(item.get("label") or item.get("name") or method_id or command).strip()
        else:
            continue
        if not command:
            continue
        if not method_id:
            method_id = f"method_{index + 1}"
        original_method_id = method_id
        suffix = 2
        while method_id in seen:
            method_id = f"{original_method_id}_{suffix}"
            suffix += 1
        seen.add(method_id)
        methods.append({"id": method_id, "label": label or method_id, "bin": command})
    return methods


def _configured_claude_from_raw_config(data: dict[str, Any]) -> tuple[str, list[dict[str, str]]]:
    providers = data.get("providers")
    if isinstance(providers, dict):
        claude = providers.get("claude")
        if isinstance(claude, dict):
            value = claude.get("bin") or claude.get("codex_bin")
            launch_methods = _normalize_launch_methods(claude.get("launch_methods") or claude.get("launchMethods"))
            if str(value or "").strip():
                return str(value).strip(), launch_methods
            if launch_methods:
                return launch_methods[0]["bin"], launch_methods

    tools = data.get("tools")
    if isinstance(tools, list):
        for item in tools:
            if not isinstance(item, dict):
                continue
            if str(item.get("name") or "").strip() != "claude":
                continue
            value = item.get("bin") or item.get("codex_bin")
            if str(value or "").strip():
                return str(value).strip(), []

    return "", []


def resolve_configured_claude_config(args: argparse.Namespace) -> tuple[str, list[dict[str, str]], str]:
    override = str(args.claude_bin or "").strip()
    if override:
        return override, [], "argument"

    candidate_paths: list[Path] = []
    if args.config:
        candidate_paths.append(Path(args.config).expanduser())
    if args.data_dir:
        candidate_paths.append(Path(args.data_dir).expanduser() / "config.yaml")
    candidate_paths.append(REPO_ROOT / "config.yaml")

    seen: set[Path] = set()
    for path in candidate_paths:
        path = path.resolve() if path.exists() else path
        if path in seen:
            continue
        seen.add(path)
        if not path.exists():
            continue
        configured, launch_methods = _configured_claude_from_raw_config(_load_yaml(path))
        if configured:
            return configured, launch_methods, str(path)

    return "claude", [], "default"


def resolve_configured_claude_bin(args: argparse.Namespace) -> tuple[str, str]:
    configured_bin, _launch_methods, source = resolve_configured_claude_config(args)
    return configured_bin, source


def _executable_available(prefix: list[str]) -> tuple[bool, str]:
    command = prefix[0] if prefix else ""
    if not command:
        return False, "empty command"
    expanded = os.path.expanduser(command)
    if os.path.sep in command:
        path = Path(expanded)
        if path.exists() and os.access(path, os.X_OK):
            return True, str(path)
        if path.exists():
            return False, f"not executable: {path}"
        return False, f"not found: {path}"
    resolved = shutil.which(command)
    if resolved:
        return True, resolved
    return False, f"not found on PATH: {command}"


def build_runtime_env_method(readiness: dict[str, Any]) -> dict[str, Any]:
    raw_runtime_env = _collect_claude_runtime_env()
    runtime_readiness = _readiness_from_runtime_env(raw_runtime_env)
    present_keys = sorted(key for key in CLAUDE_ENV_VARS if key in raw_runtime_env)
    selected = str(readiness.get("source") or "") == "runtimeEnv"

    if runtime_readiness is not None:
        sanitized = sanitize_readiness(runtime_readiness)
        return {
            "id": "runtime_env",
            "label": "Current process ANTHROPIC_* runtime env",
            "selected": selected,
            "available": bool(sanitized.get("ready")),
            "ready": bool(sanitized.get("ready")),
            "reason": sanitized.get("reason"),
            "detail": sanitized.get("detail"),
            "present_env_keys": present_keys,
        }

    return {
        "id": "runtime_env",
        "label": "Current process ANTHROPIC_* runtime env",
        "selected": selected,
        "detected": bool(present_keys),
        "available": False,
        "ready": False,
        "reason": "missingRuntimeEnv",
        "detail": "No usable current-process Claude runtime env was found.",
        "present_env_keys": present_keys,
    }


async def build_configured_cli_method(
    configured_bin: str,
    config_source: str,
    readiness: dict[str, Any],
) -> dict[str, Any]:
    prefix = resolve_claude_command_prefix(configured_bin)
    executable_available, executable_detail = _executable_available(prefix)
    selected = str(readiness.get("source") or "") != "runtimeEnv"

    sanitized = sanitize_readiness(readiness)
    return {
        "id": "configured_cli",
        "label": "Configured Claude provider CLI",
        "selected": selected,
        "detected": executable_available,
        "available": executable_available and bool(sanitized.get("ready")),
        "ready": bool(sanitized.get("ready")),
        "reason": sanitized.get("reason") or ("ok" if executable_available else "missingCli"),
        "detail": sanitized.get("detail") or executable_detail,
        "command": _safe_command_display(prefix),
        "configured": configured_bin,
        "config_source": config_source,
    }


async def build_path_claude_method(
    configured_bin: str,
    configured_cli_readiness: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved = shutil.which("claude")
    prefix = resolve_claude_command_prefix(configured_bin)
    configured_command = prefix[0] if prefix else ""
    is_configured = configured_command == "claude" or (
        bool(resolved) and os.path.expanduser(configured_command) == resolved
    )
    if not resolved:
        return {
            "id": "path_claude",
            "label": "PATH claude executable",
            "selected": False,
            "detected": False,
            "available": False,
            "ready": False,
            "reason": "missingCli",
            "detail": "claude was not found on PATH.",
            "command": "claude",
        }

    if is_configured and isinstance(configured_cli_readiness, dict):
        readiness = configured_cli_readiness
    else:
        readiness = await ClaudeAdapter(claude_bin="claude")._check_cli_readiness_for_prefix(["claude"])
    sanitized = sanitize_readiness(readiness)
    return {
        "id": "path_claude",
        "label": "PATH claude executable",
        "selected": False,
        "detected": True,
        "available": bool(sanitized.get("ready")),
        "ready": bool(sanitized.get("ready")),
        "reason": "configured" if is_configured and sanitized.get("ready") else sanitized.get("reason"),
        "detail": sanitized.get("detail") or resolved,
        "command": "claude",
    }


def build_ow_claude_method(configured_bin: str) -> dict[str, Any]:
    wrapper = REPO_ROOT / "scripts" / "ow-claude"
    available = wrapper.exists() and os.access(wrapper, os.X_OK)
    configured = str(configured_bin or "").strip()
    selected = configured == str(wrapper) or configured.endswith("/scripts/ow-claude")
    return {
        "id": "ow_claude_wrapper",
        "label": "OnlineWorker ow-claude wrapper",
        "selected": selected,
        "detected": available,
        "available": False,
        "ready": None,
        "reason": "configured" if selected else ("wrapperAvailable" if available else "missingWrapper"),
        "detail": (
            "Wrapper entrypoint exists, but it is only a configurable candidate and is not proof that Claude provider can send."
            if available
            else "scripts/ow-claude was not found or is not executable."
        ),
        "command": str(wrapper),
    }


def _owner_bridge_request(socket_path: Path, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
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


def sanitize_owner_bridge_status(status: dict[str, Any] | None) -> dict[str, Any]:
    data = status if isinstance(status, dict) else {}
    sanitized: dict[str, Any] = {}
    for key in ("ok", "health", "detail", "lines", "error"):
        if key in data:
            sanitized[key] = data[key]
    return sanitized


async def collect_readiness(args: argparse.Namespace) -> dict[str, Any]:
    configured_bin, launch_methods, config_source = resolve_configured_claude_config(args)
    adapter = ClaudeAdapter(claude_bin=configured_bin, launch_methods=launch_methods or None)
    readiness = await adapter.check_readiness(force=True)
    sanitized_readiness = sanitize_readiness(readiness)
    configured_methods = readiness.get("methods") if isinstance(readiness.get("methods"), list) else []
    if configured_methods:
        methods = [build_runtime_env_method(readiness), *configured_methods]
        configured_cli_readiness = None
    else:
        configured_cli_readiness = (
            readiness
            if str(readiness.get("source") or "") != "runtimeEnv"
            else await adapter._check_cli_readiness_for_prefix(resolve_claude_command_prefix(configured_bin))
        )
        methods = [
            build_runtime_env_method(readiness),
            await build_configured_cli_method(configured_bin, config_source, configured_cli_readiness),
        ]
    methods.extend([
        await build_path_claude_method(configured_bin, configured_cli_readiness),
        build_ow_claude_method(configured_bin),
    ])
    result: dict[str, Any] = {
        "provider": "claude",
        "configured_bin": {
            "value": configured_bin,
            "source": config_source,
        },
        "configured_launch_methods": launch_methods,
        "readiness": sanitized_readiness,
        "methods": [sanitize_method(method) for method in methods],
    }

    if args.owner_bridge_status:
        socket_path = Path(args.owner_bridge_socket).expanduser()
        try:
            status = _owner_bridge_request(
                socket_path,
                {
                    "type": "runtime_status",
                    "provider_id": "claude",
                },
                args.timeout,
            )
            result["owner_bridge_status"] = sanitize_owner_bridge_status(status)
            result["methods"].append(
                sanitize_method(
                    {
                        "id": "owner_bridge_status",
                        "label": "Running OnlineWorker owner bridge runtime status",
                        "selected": False,
                        "detected": status.get("ok") is True,
                        "available": status.get("ok") is True,
                        "ready": status.get("health") == "healthy",
                        "reason": str(status.get("health") or status.get("error") or "unknown"),
                        "detail": status.get("detail") or status.get("error"),
                    }
                )
            )
        except Exception as exc:
            result["owner_bridge_status"] = {
                "ok": False,
                "error": str(exc),
            }
            result["methods"].append(
                sanitize_method(
                    {
                        "id": "owner_bridge_status",
                        "label": "Running OnlineWorker owner bridge runtime status",
                        "selected": False,
                        "detected": False,
                        "available": False,
                        "ready": False,
                        "reason": "ownerBridgeUnavailable",
                        "detail": str(exc),
                    }
                )
            )

    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Diagnose Claude provider readiness using the real local Claude CLI/runtime env. "
            "Output is sanitized and never includes tokens or raw environment values."
        )
    )
    parser.add_argument("--claude-bin", default=None, help="Override the configured Claude provider bin.")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR), help="OnlineWorker data dir used to locate config.yaml.")
    parser.add_argument("--config", default=None, help="Explicit OnlineWorker config.yaml path.")
    parser.add_argument(
        "--owner-bridge-status",
        action="store_true",
        help="Also query the running OnlineWorker provider owner bridge runtime_status for Claude.",
    )
    parser.add_argument("--owner-bridge-socket", default=str(DEFAULT_OWNER_BRIDGE_SOCKET))
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument(
        "--fail-on-unavailable",
        action="store_true",
        help="Exit with code 2 when readiness.ready is false.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    result = asyncio.run(collect_readiness(args))
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    readiness = result.get("readiness")
    if args.fail_on_unavailable and isinstance(readiness, dict) and readiness.get("ready") is not True:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
