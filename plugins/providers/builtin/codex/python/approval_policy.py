from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any


SOURCE_APP_SERVER = "app_server"
SOURCE_CLI_HOOK = "codex_cli_hook"
SOURCE_PROVIDER_HOOK_MIRROR = "provider_hook_mirror"
SOURCE_REMOTE_PROXY = "codex_remote_proxy"
SOURCE_TUI_HOST = "codex_tui_host"

APP_SERVER_APPROVAL_SOURCES = frozenset(
    {
        SOURCE_APP_SERVER,
        "execCommandApproval",
        "applyPatchApproval",
    }
)

NOTICE_BLOCKING_HOOK_CONTROL = "此请求已进入 Codex CLI blocking hook，可在 TG 中处理。"
NOTICE_CLI_NATIVE_MIRROR_ONLY = "此请求由 Codex CLI 原生审批处理，TG 仅同步通知。"
NOTICE_CLI_OR_TG_CONTROL = "此请求已在 Codex CLI 中弹出，可在 CLI 或 TG 中处理。"
NOTICE_REMOTE_PROXY_CONTROL = "此请求已在 Codex CLI 中弹出，可在 CLI 或 TG 中处理。"

_TRUE_VALUES = {"1", "true", "yes", "on", "blocking"}


def is_app_server_approval_source(source: str) -> bool:
    normalized = str(source or "")
    return normalized.startswith("item/") or normalized in APP_SERVER_APPROVAL_SOURCES


def is_hook_control_enabled(
    payload: Mapping[str, Any] | None,
    *,
    env: Mapping[str, str] | None = None,
) -> bool:
    payload = payload or {}
    value = str(payload.get("onlineworker_codex_hook_control") or "").strip().lower()
    if value in _TRUE_VALUES:
        return True
    env_value = str((env or os.environ).get("ONLINEWORKER_CODEX_HOOK_CONTROL") or "").strip().lower()
    return env_value in _TRUE_VALUES


def hook_notice_suffix(*, hook_control_enabled: bool) -> str:
    return NOTICE_BLOCKING_HOOK_CONTROL if hook_control_enabled else NOTICE_CLI_NATIVE_MIRROR_ONLY


def build_mirror_approval_policy(
    request: Mapping[str, Any],
    *,
    thread_id: str,
    can_route_to_tui_host: bool,
) -> dict[str, Any]:
    if request.get("blocking"):
        return {
            "interactive": True,
            "approval_source": str(request.get("source") or SOURCE_CLI_HOOK),
            "notice_suffix": NOTICE_BLOCKING_HOOK_CONTROL,
        }
    if can_route_to_tui_host:
        return {
            "interactive": True,
            "request_id": f"codex-tui-host:{thread_id}",
            "approval_source": SOURCE_TUI_HOST,
            "notice_suffix": NOTICE_CLI_OR_TG_CONTROL,
        }
    return {
        "interactive": False,
        "approval_source": str(request.get("source") or SOURCE_PROVIDER_HOOK_MIRROR),
        "notice_suffix": str(request.get("notice_suffix") or NOTICE_CLI_NATIVE_MIRROR_ONLY),
    }
