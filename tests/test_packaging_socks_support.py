from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_requirements_include_socksio_runtime_dependency() -> None:
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "socksio" in requirements


def test_pyinstaller_specs_include_socksio_hiddenimport() -> None:
    spec_paths = [
        ROOT / "onlineworker.spec",
        ROOT / "onlineworker-x86_64.spec",
    ]
    for spec_path in spec_paths:
        spec_text = spec_path.read_text(encoding="utf-8")
        assert "'socksio'" in spec_text, spec_path.name


def test_pyinstaller_specs_bundle_builtin_provider_manifests() -> None:
    spec_paths = [
        ROOT / "onlineworker.spec",
        ROOT / "onlineworker-x86_64.spec",
    ]
    for spec_path in spec_paths:
        spec_text = spec_path.read_text(encoding="utf-8")
        assert "'plugins/providers/builtin/claude/plugin.yaml'" in spec_text, spec_path.name
        assert "'plugins/providers/builtin/codex/plugin.yaml'" in spec_text, spec_path.name


def test_packaging_includes_lightweight_claude_hook_relay() -> None:
    spec_paths = [
        ROOT / "onlineworker.spec",
        ROOT / "onlineworker-x86_64.spec",
    ]
    for spec_path in spec_paths:
        spec_text = spec_path.read_text(encoding="utf-8")
        assert "'plugins/providers/builtin/claude/python/claude_hook_relay.py'" in spec_text, spec_path.name

    tauri_config = (ROOT / "mac-app/src-tauri/tauri.conf.json").read_text(encoding="utf-8")
    assert '"hook-relays"' in tauri_config


def test_pyinstaller_specs_include_packaged_ow_codex_entrypoint() -> None:
    spec_paths = [
        ROOT / "onlineworker.spec",
        ROOT / "onlineworker-x86_64.spec",
    ]
    for spec_path in spec_paths:
        spec_text = spec_path.read_text(encoding="utf-8")
        assert "'plugins.providers.builtin.codex.python.cli_wrapper'" in spec_text, spec_path.name
