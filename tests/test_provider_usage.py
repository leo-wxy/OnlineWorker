from core import provider_usage as bridge
from core.providers.contracts import (
    ProviderDescriptor,
    ProviderMetadata,
)


def test_load_provider_descriptor_prefers_registry_for_bundled_provider(monkeypatch):
    descriptor = object()

    monkeypatch.setattr(bridge, "get_provider", lambda provider_id: descriptor if provider_id == "codex" else None)
    monkeypatch.setattr(bridge, "_iter_provider_plugin_manifests", lambda: [])

    assert bridge._load_provider_descriptor("codex") is descriptor


def test_load_provider_descriptor_falls_back_to_manifest_scan(monkeypatch, tmp_path):
    overlay_dir = tmp_path / "provider-plugins" / "overlay-tool"
    overlay_dir.mkdir(parents=True)
    module_name = "bridge_overlay_manifest_entry"
    (overlay_dir / "plugin.yaml").write_text(
        """
schema_version: 1
id: overlay-tool
kind: provider
label: Overlay Tool
entrypoints:
  python_descriptor: {module_name}:create_provider_descriptor
""".format(module_name=module_name).strip()
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "provider-plugins" / f"{module_name}.py").write_text(
        """
from core.providers.contracts import ProviderDescriptor, ProviderFactsHooks, ProviderMetadata, ProviderUsageHooks

def create_provider_descriptor():
    return ProviderDescriptor(
        name="overlay-tool",
        metadata=ProviderMetadata(id="overlay-tool", label="Overlay Tool"),
        facts=ProviderFactsHooks(
            scan_workspaces=lambda **_kwargs: [],
            list_threads=lambda *_args, **_kwargs: [],
            read_thread_history=lambda *_args, **_kwargs: [],
            query_active_thread_ids=lambda *_args, **_kwargs: set(),
        ),
        usage_hooks=ProviderUsageHooks(get_summary=lambda start_date, end_date: {"days": []}),
    )
""".strip()
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(bridge, "get_provider", lambda provider_id: None)
    monkeypatch.setattr(bridge, "_iter_provider_plugin_manifests", lambda: [overlay_dir / "plugin.yaml"])

    descriptor = bridge._load_provider_descriptor("overlay-tool")

    assert isinstance(descriptor, ProviderDescriptor)
    assert descriptor.name == "overlay-tool"
    assert descriptor.metadata == ProviderMetadata(id="overlay-tool", label="Overlay Tool")


def test_provider_usage_summary_invokes_descriptor_usage_hook(monkeypatch):
    called = {}

    class UsageHooks:
        @staticmethod
        def get_summary(start_date, end_date):
            called["range"] = (start_date, end_date)
            return {
                "days": [
                    {
                        "date": "2026-05-21",
                        "inputTokens": 12,
                        "outputTokens": 3,
                        "cacheCreationTokens": 4,
                        "cacheReadTokens": 5,
                        "totalTokens": 24,
                        "totalCostUsd": 0.42,
                    }
                ]
            }

    class Descriptor:
        usage_hooks = UsageHooks

    monkeypatch.setattr(bridge, "_load_provider_descriptor", lambda provider_id: Descriptor())
    monkeypatch.setattr(bridge, "_unix_time_seconds", lambda: 1770000000)

    result = bridge.get_provider_usage_summary(
        "overlay-tool",
        "2026-05-20",
        "2026-05-21",
    )

    assert called["range"] == ("2026-05-20", "2026-05-21")
    assert result == {
        "providerId": "overlay-tool",
        "days": [
            {
                "date": "2026-05-21",
                "inputTokens": 12,
                "outputTokens": 3,
                "cacheCreationTokens": 4,
                "cacheReadTokens": 5,
                "totalTokens": 24,
                "totalCostUsd": 0.42,
            }
        ],
        "updatedAtEpoch": 1770000000,
        "unsupportedReason": None,
    }


def test_provider_usage_summary_rejects_provider_without_usage_hook(monkeypatch):
    class Descriptor:
        usage_hooks = None

    monkeypatch.setattr(bridge, "_load_provider_descriptor", lambda provider_id: Descriptor())

    try:
        bridge.get_provider_usage_summary(
            "overlay-tool",
            "2026-05-20",
            "2026-05-21",
        )
    except ValueError as exc:
        assert str(exc) == "Provider 'overlay-tool' does not expose usage hooks"
    else:
        raise AssertionError("expected missing usage hook error")


def test_codex_provider_usage_summary_reads_session_token_counts(monkeypatch, tmp_path):
    from plugins.providers.builtin.codex.python import storage_runtime

    sessions_dir = tmp_path / "codex-sessions"
    day_dir = sessions_dir / "2026" / "05" / "11"
    day_dir.mkdir(parents=True)
    (day_dir / "rollout.jsonl").write_text(
        "\n".join(
            [
                '{"type":"session_meta","payload":{"id":"t1"}}',
                '{"timestamp":"2026-05-11T01:00:00.000Z","type":"event_msg","payload":{"type":"token_count","info":{"last_token_usage":{"input_tokens":100,"cached_input_tokens":10,"output_tokens":50,"total_tokens":150},"total_token_usage":{"input_tokens":100,"cached_input_tokens":10,"output_tokens":50,"total_tokens":150}}}}',
                '{"timestamp":"2026-05-11T03:00:00.000Z","type":"event_msg","payload":{"type":"token_count","info":{"total_token_usage":{"input_tokens":160,"cached_input_tokens":20,"output_tokens":70,"total_tokens":230}}}}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(storage_runtime, "CODEX_SESSIONS_DIR", str(sessions_dir))
    monkeypatch.setattr(bridge, "_unix_time_seconds", lambda: 1770000000)

    result = bridge.get_provider_usage_summary("codex", "2026-05-11", "2026-05-11")

    assert result == {
        "providerId": "codex",
        "days": [
            {
                "date": "2026-05-11",
                "inputTokens": 160,
                "outputTokens": 70,
                "cacheCreationTokens": 0,
                "cacheReadTokens": 20,
                "totalTokens": 230,
                "totalCostUsd": None,
            }
        ],
        "updatedAtEpoch": 1770000000,
        "unsupportedReason": None,
    }


def test_claude_provider_usage_summary_reads_project_usage(monkeypatch, tmp_path):
    from plugins.providers.builtin.claude.python import storage_runtime

    projects_dir = tmp_path / "claude-projects"
    project_dir = projects_dir / "project-a"
    project_dir.mkdir(parents=True)
    (project_dir / "session.jsonl").write_text(
        "\n".join(
            [
                '{"timestamp":"2026-05-11T10:00:00.000Z","requestId":"req-1","message":{"id":"msg-1","usage":{"input_tokens":100,"output_tokens":50,"cache_creation_input_tokens":20,"cache_read_input_tokens":10}},"costUSD":0.12}',
                '{"timestamp":"2026-05-11T10:00:01.000Z","requestId":"req-1","message":{"id":"msg-1","usage":{"input_tokens":100,"output_tokens":50,"cache_creation_input_tokens":20,"cache_read_input_tokens":10}},"costUSD":0.12}',
                '{"timestamp":"2026-05-11T11:00:00.000Z","requestId":"req-2","message":{"id":"msg-2","usage":{"input_tokens":40,"output_tokens":10}},"costUSD":0.08}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(storage_runtime, "CLAUDE_PROJECTS_DIR", str(projects_dir))
    monkeypatch.setattr(bridge, "_unix_time_seconds", lambda: 1770000000)

    result = bridge.get_provider_usage_summary("claude", "2026-05-11", "2026-05-11")

    assert result == {
        "providerId": "claude",
        "days": [
            {
                "date": "2026-05-11",
                "inputTokens": 140,
                "outputTokens": 60,
                "cacheCreationTokens": 20,
                "cacheReadTokens": 10,
                "totalTokens": 230,
                "totalCostUsd": 0.2,
            }
        ],
        "updatedAtEpoch": 1770000000,
        "unsupportedReason": None,
    }
