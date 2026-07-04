from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_versions() -> dict[str, str]:
    package_json = json.loads((ROOT / "mac-app/package.json").read_text(encoding="utf-8"))
    cargo_toml = (ROOT / "mac-app/src-tauri/Cargo.toml").read_text(encoding="utf-8")
    tauri_conf = json.loads((ROOT / "mac-app/src-tauri/tauri.conf.json").read_text(encoding="utf-8"))

    cargo_version = re.search(r'^version = "([^"]+)"$', cargo_toml, re.MULTILINE)
    assert cargo_version is not None

    return {
        "VERSION": (ROOT / "VERSION").read_text(encoding="utf-8").strip(),
        "package.json": package_json["version"],
        "Cargo.toml": cargo_version.group(1),
        "tauri.conf.json": tauri_conf["version"],
    }


def test_app_packaging_versions_match_single_version_file():
    versions = read_versions()

    assert len(set(versions.values())) == 1, versions


def test_build_script_syncs_versions_before_packaging():
    build_script = (ROOT / "scripts/build.sh").read_text(encoding="utf-8")

    assert "scripts/sync-app-version.py" in build_script
    assert "=== Sync app version ===" in build_script


def test_build_script_keeps_frontend_dependency_setup_non_interactive():
    build_script = (ROOT / "scripts/build.sh").read_text(encoding="utf-8")

    assert "check_frontend_package_manager_state" in build_script
    assert "pnpm-lock.yaml" in build_script
    assert "pnpm-workspace.yaml" in build_script
    assert "npm install --no-package-lock" in build_script
    assert "npm run tauri -- build" in build_script
    assert "pnpm tauri build" not in build_script
    assert "pnpm install" not in build_script
    assert "PUPPETEER_SKIP_DOWNLOAD" in build_script


def test_mac_app_does_not_depend_on_pnpm_build_script_approvals():
    package_json = json.loads((ROOT / "mac-app/package.json").read_text(encoding="utf-8"))

    assert "pnpm" not in package_json


def test_sync_app_version_updates_all_packaging_version_fields(tmp_path):
    fixture = tmp_path / "repo"
    (fixture / "mac-app/src-tauri").mkdir(parents=True)
    (fixture / "scripts").mkdir()
    (fixture / "VERSION").write_text("9.8.7\n", encoding="utf-8")
    (fixture / "mac-app/package.json").write_text(
        json.dumps({"name": "fixture", "version": "0.0.1"}, indent=2) + "\n",
        encoding="utf-8",
    )
    (fixture / "mac-app/src-tauri/Cargo.toml").write_text(
        '[package]\nname = "fixture"\nversion = "0.0.1"\n',
        encoding="utf-8",
    )
    (fixture / "mac-app/src-tauri/tauri.conf.json").write_text(
        json.dumps({"productName": "Fixture", "version": "0.0.1"}, indent=2) + "\n",
        encoding="utf-8",
    )

    subprocess.run(
        [
            "python3",
            str(ROOT / "scripts/sync-app-version.py"),
            "--root",
            str(fixture),
        ],
        check=True,
    )

    assert json.loads((fixture / "mac-app/package.json").read_text(encoding="utf-8"))[
        "version"
    ] == "9.8.7"
    assert 'version = "9.8.7"' in (
        fixture / "mac-app/src-tauri/Cargo.toml"
    ).read_text(encoding="utf-8")
    assert json.loads(
        (fixture / "mac-app/src-tauri/tauri.conf.json").read_text(encoding="utf-8")
    )["version"] == "9.8.7"
