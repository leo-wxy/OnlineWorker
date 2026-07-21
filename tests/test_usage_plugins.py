import pytest

from core.usage.registry import (
    clear_usage_registry_cache,
    get_provider_usage_source,
    get_usage_source_catalog,
    load_usage_plugins,
)
from core.usage import registry


@pytest.fixture(autouse=True)
def reset_usage_registry_cache():
    clear_usage_registry_cache()
    yield
    clear_usage_registry_cache()


def test_ccusage_plugin_exposes_all_pinned_sources(monkeypatch):
    monkeypatch.delenv("ONLINEWORKER_PROVIDER_OVERLAY", raising=False)
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


def test_usage_catalog_skips_broken_provider_manifest(monkeypatch, tmp_path, caplog):
    overlay = tmp_path / "providers" / "broken"
    overlay.mkdir(parents=True)
    (overlay / "plugin.yaml").write_text(
        """
schema_version: 1
id: broken
kind: provider
provider: invalid
entrypoints:
  python_descriptor: broken:create_provider_descriptor
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("ONLINEWORKER_PROVIDER_OVERLAY", str(tmp_path / "providers"))

    catalog = get_usage_source_catalog()

    assert [item["sourceId"] for item in catalog[:3]] == ["codex", "claude", "opencode"]
    assert "Skipping provider usage association that failed to load" in caplog.text


def test_usage_registry_keeps_last_successful_snapshot_when_manifests_disappear(monkeypatch):
    plugins = load_usage_plugins()
    catalog = get_usage_source_catalog()

    monkeypatch.setattr(registry, "_manifest_paths", lambda: [])

    assert load_usage_plugins() == plugins
    assert get_usage_source_catalog() == catalog


def test_usage_catalog_returns_isolated_nested_metadata():
    catalog = get_usage_source_catalog()
    assert catalog

    catalog[0]["icon"]["path"] = "changed.svg"

    assert get_usage_source_catalog()[0]["icon"].get("path") != "changed.svg"


def test_usage_plugins_return_isolated_manifests():
    plugins = load_usage_plugins()
    plugins["ccusage"][0]["sources"][0]["label"] = "Changed"

    assert load_usage_plugins()["ccusage"][0]["sources"][0]["label"] != "Changed"
