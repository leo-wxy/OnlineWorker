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


def _load_spec_globals(spec_path: Path) -> dict:
    source = spec_path.read_text(encoding="utf-8")
    prefix = source.split("a = Analysis(", 1)[0]
    return _exec_spec_prefix(prefix, spec_path)


def _exec_spec_prefix(source: str, spec_path: Path) -> dict:
    globals_dict = {"__file__": str(spec_path)}
    exec(compile(source, str(spec_path), "exec"), globals_dict)
    return globals_dict


def test_pyinstaller_specs_bundle_dynamic_provider_python_modules() -> None:
    spec_paths = [
        ROOT / "onlineworker.spec",
        ROOT / "onlineworker-x86_64.spec",
    ]
    required_hiddenimports = [
        "plugins.providers.builtin.claude.python.config_normalizer",
        "plugins.providers.builtin.claude.python.provider",
        "plugins.providers.builtin.codex.python.config_normalizer",
        "plugins.providers.builtin.codex.python.provider",
    ]
    for spec_path in spec_paths:
        spec_globals = _load_spec_globals(spec_path)
        hiddenimports = spec_globals["provider_hiddenimports"]
        for hiddenimport in required_hiddenimports:
            assert hiddenimport in hiddenimports, f"{hiddenimport} missing from {spec_path.name}"
