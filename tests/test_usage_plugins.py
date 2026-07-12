from core.usage.registry import (
    get_provider_usage_source,
    get_usage_source_catalog,
    load_usage_plugins,
)


def test_ccusage_plugin_exposes_all_pinned_sources():
    plugins = load_usage_plugins()
    assert set(plugins) == {"ccusage"}
    catalog = get_usage_source_catalog()
    assert [item["sourceId"] for item in catalog] == [
        "codex", "claude", "opencode", "amp", "droid", "codebuff", "hermes", "pi",
        "goose", "openclaw", "kilo", "copilot", "gemini", "kimi", "qwen",
    ]
    associated = {
        item["sourceId"]: item["providerId"]
        for item in catalog
        if item["providerId"]
    }
    assert associated == {"claude": "claude", "codex": "codex"}


def test_usage_catalog_associates_overlay_provider(monkeypatch, tmp_path):
    overlay = tmp_path / "providers" / "opencode"
    overlay.mkdir(parents=True)
    (overlay / "plugin.yaml").write_text(
        """
schema_version: 1
id: opencode
kind: provider
label: OpenCode
provider:
  usage:
    plugin_id: ccusage
    source_id: opencode
entrypoints:
  python_descriptor: unused:create_provider_descriptor
""".strip() + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ONLINEWORKER_PROVIDER_OVERLAY", str(tmp_path / "providers"))

    catalog = get_usage_source_catalog()

    opencode = next(item for item in catalog if item["sourceId"] == "opencode")
    assert opencode["providerId"] == "opencode"
    assert get_provider_usage_source("opencode") == ("ccusage", "opencode")
