from __future__ import annotations

SOURCE_APP_SERVER = "app_server"
SOURCE_REMOTE_PROXY = "codex_remote_proxy"
SOURCE_TUI_HOST = "codex_tui_host"

APP_SERVER_APPROVAL_SOURCES = frozenset(
    {
        SOURCE_APP_SERVER,
        "execCommandApproval",
        "applyPatchApproval",
    }
)

NOTICE_REMOTE_PROXY_CONTROL = "此请求已在 Codex CLI 中弹出，可在 CLI 或 TG 中处理。"


def is_app_server_approval_source(source: str) -> bool:
    normalized = str(source or "")
    return normalized.startswith("item/") or normalized in APP_SERVER_APPROVAL_SOURCES
