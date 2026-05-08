from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_lifecycle_manager_does_not_embed_provider_specific_runtime() -> None:
    source = (PROJECT_ROOT / "core" / "lifecycle.py").read_text(encoding="utf-8")

    disallowed_tokens = [
        "CodexAdapter",
        "AppServerProcess",
        "is_codex_local_owner_mode",
        "start_codex_tui_sync_loop",
        "start_codex_tui_realtime_mirror_loop",
        "clear_codex_tui_diagnostics_snapshot",
        "clear_stale_host_artifacts",
        "_start_codex",
        "_shutdown_codex",
        "_connect_adapter_with_retry",
        "_schedule_codex_reconnect",
        "_recover_stale_codex_stream",
        "_sync_existing_claude_topics",
        "_start_claude",
        "_shutdown_claude",
        "_start_customprovider",
        "_shutdown_customprovider",
    ]

    for token in disallowed_tokens:
        assert token not in source


def test_provider_specific_runtime_modules_live_under_plugins() -> None:
    removed_core_modules = [
        "core/claude",
        "core/customprovider",
        "core/codex_runtime",
        "core/codex_adapter.py",
        "core/codex_hook_bridge.py",
        "core/codex_owner_bridge.py",
        "core/codex_tui_bridge.py",
        "core/codex_tui_host_client.py",
        "core/codex_tui_host_protocol.py",
        "core/codex_tui_host_runtime.py",
        "core/codex_tui_realtime_mirror.py",
        "core/process.py",
    ]
    for relative_path in removed_core_modules:
        assert not (PROJECT_ROOT / relative_path).exists()

    plugin_runtime_modules = [
        "plugins/providers/builtin/codex/python/adapter.py",
        "plugins/providers/builtin/codex/python/process.py",
        "plugins/providers/builtin/codex/python/hook_bridge.py",
        "plugins/providers/builtin/codex/python/owner_bridge.py",
        "plugins/providers/builtin/codex/python/tui_bridge.py",
        "plugins/providers/builtin/codex/python/semantic_events.py",
        "plugins/providers/builtin/claude/python/adapter.py",
        "plugins/providers/builtin/claude/python/hook_bridge.py",
    ]
    for relative_path in plugin_runtime_modules:
        assert (PROJECT_ROOT / relative_path).is_file()

    assert not (PROJECT_ROOT / "plugins" / "providers" / "private").exists()


def test_core_runtime_files_remain_provider_generic() -> None:
    core_files = [
        PROJECT_ROOT / "core" / "state.py",
        PROJECT_ROOT / "core" / "storage.py",
        PROJECT_ROOT / "core" / "lifecycle.py",
    ]
    for path in core_files:
        source = path.read_text(encoding="utf-8")
        for token in ("codex", "claude", "customprovider", "state.adapter"):
            assert token not in source
