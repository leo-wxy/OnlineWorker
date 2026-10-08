import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("arch,target,spec", [
    ("arm64", "aarch64-apple-darwin", "onlineworker.spec"),
    ("x86_64", "x86_64-apple-darwin", "onlineworker-x86_64.spec"),
])
@pytest.mark.parametrize("sign_updater", [False, True])
def test_shared_build_targets_python_sidecars_and_tauri_together(tmp_path, arch, target, spec, sign_updater):
    # All build tools are synthetic; this test never builds or mounts a real app.
    fixture = tmp_path / "repo"
    scripts = fixture / "scripts"
    scripts.mkdir(parents=True)
    for name in ("build.sh", "sync-app-version.py"):
        shutil.copyfile(ROOT / "scripts" / name, scripts / name)
    tauri = fixture / "mac-app/src-tauri"
    tauri.mkdir(parents=True)
    (fixture / "VERSION").write_text("9.8.7\n")
    (fixture / "mac-app/package.json").write_text(json.dumps({"version": "9.8.7"}))
    (tauri / "Cargo.toml").write_text('[package]\nversion = "9.8.7"\n')
    (tauri / "tauri.conf.json").write_text(json.dumps({"version": "9.8.7"}))
    manifest = fixture / "third_party/ccusage/rust/crates/ccusage/Cargo.toml"
    manifest.parent.mkdir(parents=True)
    manifest.touch()
    relay = fixture / "plugins/providers/builtin/claude/python/claude_hook_relay.py"
    relay.parent.mkdir(parents=True)
    relay.touch()
    cli = fixture / "mac-app/node_modules/.bin/tauri"
    cli.parent.mkdir(parents=True)
    cli.touch()
    cli.chmod(0o755)
    tools = tmp_path / "tools"
    tools.mkdir()
    stubs = {
        "rustc": 'printf "host: %s\\n" "$BUILD_TEST_TARGET"',
        "uname": 'echo "$BUILD_TEST_ARCH"',
        "hdiutil": 'exit 0',
        "python exe": 'if [ "$1" = "-c" ]; then echo "$BUILD_TEST_ARCH"; else printf "%s\\n" "$*" >> "$BUILD_TEST_LOG"; mkdir -p "$BUILD_TEST_ROOT/dist"; echo bot > "$BUILD_TEST_ROOT/dist/onlineworker-bot"; fi',
        "cargo": 'printf "%s\\n" "$*" >> "$BUILD_TEST_LOG"; mkdir -p "$BUILD_TEST_ROOT/third_party/ccusage/rust/target/$BUILD_TEST_TARGET/release"; echo usage > "$BUILD_TEST_ROOT/third_party/ccusage/rust/target/$BUILD_TEST_TARGET/release/ccusage"',
        "npm": 'printf "%s\\n" "$*" >> "$BUILD_TEST_LOG"; mkdir -p "$BUILD_TEST_ROOT/mac-app/src-tauri/target/$BUILD_TEST_TARGET/release/bundle/dmg"; echo mock > "$BUILD_TEST_ROOT/mac-app/src-tauri/target/$BUILD_TEST_TARGET/release/bundle/dmg/sample.dmg"',
    }
    for name, body in stubs.items():
        path = tools / name
        path.write_text("#!/bin/bash\nset -eu\n" + body + "\n")
        path.chmod(0o755)
    log = tmp_path / "calls"
    env = {**os.environ, "PATH": str(tools) + os.pathsep + os.environ["PATH"],
           "BUILD_TEST_TARGET": target, "BUILD_TEST_ARCH": arch, "BUILD_TEST_ROOT": str(fixture),
           "BUILD_TEST_LOG": str(log), "ONLINEWORKER_TARGET_TRIPLE": target,
           "PYTHON_EXECUTABLE": str(tools / "python exe"), "ONLINEWORKER_PLUGIN_SOURCE_DIRS": "",
           "TAURI_SIGNING_PRIVATE_KEY": "synthetic-updater-signing-key",
           "ONLINEWORKER_NOTIFICATION_PLUGIN_SOURCE_DIRS": ""}
    if not sign_updater:
        env.pop("TAURI_SIGNING_PRIVATE_KEY", None)
    result = subprocess.run(["bash", str(scripts / "build.sh")], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    calls = log.read_text()
    assert f"-m PyInstaller {spec} --clean --noconfirm" in calls
    assert f"--release --locked --target {target}" in calls
    assert f"run tauri -- build --target {target}" in calls
    assert ('--config {"bundle":{"createUpdaterArtifacts":false}}' in calls) is (not sign_updater)
    assert (tauri / f"binaries/onlineworker-bot-{target}").read_text().strip() == "bot"
    assert (tauri / f"binaries/ccusage-{target}").read_text().strip() == "usage"
    assert f"target/{target}/release/bundle/dmg/sample.dmg" in result.stdout


def test_release_workflow_validates_both_architectures_before_publishing():
    workflow = yaml.safe_load((ROOT / ".github/workflows/release-dmg.yml").read_text())
    build = workflow["jobs"]["build-dmg"]
    assert {row["target"] for row in build["strategy"]["matrix"]["include"]} == {
        "aarch64-apple-darwin", "x86_64-apple-darwin"}
    assert workflow["jobs"]["publish-release"]["needs"] == "build-dmg"
    steps = {step.get("name"): step for step in build["steps"]}
    assert '--check --tag "$RELEASE_TAG"' in steps["Check tag and packaging versions"]["run"]
    assert 'if [ "$SIGNED_RELEASE" = true ]; then' in steps["Build DMG"]["run"]
    assert "steps.python.outputs.python-path" in steps["Build DMG"]["env"]["PYTHON_EXECUTABLE"]
    assert "|| '-'" in steps["Build DMG"]["env"]["APPLE_SIGNING_IDENTITY"]
    assert "xcrun stapler validate" in steps["Verify app version, architecture and signing"]["run"]
    for job in workflow["jobs"].values():
        for step in job["steps"]:
            if "run" in step:
                checked = subprocess.run(["bash", "-n"], input=step["run"], text=True, capture_output=True)
                assert checked.returncode == 0, checked.stderr


@pytest.mark.parametrize("fallback", [False, True])
def test_dmg_release_build_and_publish_do_not_require_updater_keys(tmp_path, fallback):
    workflow = yaml.safe_load((ROOT / ".github/workflows/release-dmg.yml").read_text())
    steps = {step.get("name"): step for step in workflow["jobs"]["build-dmg"]["steps"]}
    assert "TAURI_SIGNING_PRIVATE_KEY" not in json.dumps(workflow)
    assert steps["Upload workflow artifact"]["with"]["path"] == "${{ env.BUNDLE_ROOT }}/dmg/*.dmg"

    # Execute the real workflow shell steps with synthetic build tools and DMGs.
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    bundle = tmp_path / "bundle"
    dmg_script = 'mkdir -p "$BUNDLE_ROOT/dmg"\nprintf dmg > "$BUNDLE_ROOT/dmg/OnlineWorker_9.8.7_arm64.dmg"\nprintf dmg > "$BUNDLE_ROOT/dmg/OnlineWorker_9.8.7_x86_64.dmg"\n'
    (scripts / "build.sh").write_text("exit 1\n" if fallback else dmg_script)
    (scripts / "create-dmg-from-app.sh").write_text(dmg_script)
    env = {**os.environ, "BUNDLE_ROOT": str(bundle), "SIGNED_RELEASE": "false",
           "TAURI_SIGNING_PRIVATE_KEY": "", "TAURI_SIGNING_PRIVATE_KEY_PASSWORD": ""}
    result = subprocess.run(["bash", "-e", "-c", steps["Build DMG"]["run"]], cwd=tmp_path,
                            env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    dmgs = sorted((bundle / "dmg").glob("*.dmg"))
    assert len(dmgs) == 2

    # A single upload path puts these filenames at the artifact root.
    downloaded = tmp_path / "release-dmg"
    downloaded.mkdir()
    for dmg in dmgs:
        shutil.copyfile(dmg, downloaded / dmg.name)
    log = tmp_path / "gh-calls"
    gh = tmp_path / "gh"
    gh.write_text(
        '#!/bin/bash\nset -eu\nprintf "%s\\n" "$*" >> "$TEST_GH_LOG"\n'
        'case "$1 $2" in\n'
        '  "release view") exit 1 ;;\n'
        '  "release upload") shift 3; for file in "$@"; do\n'
        '    [ "$file" = "--clobber" ] && continue\n'
        '    [[ "$file" == *.dmg ]] && test -s "$file"\n'
        '  done ;;\nesac\n'
    )
    gh.chmod(0o755)
    publish = next(step["run"] for step in workflow["jobs"]["publish-release"]["steps"] if "run" in step)
    result = subprocess.run(["bash", "-e", "-c", publish], cwd=tmp_path,
                            env={**env, "PATH": str(tmp_path) + os.pathsep + env["PATH"],
                                 "RELEASE_TAG": "9.8.7", "TEST_GH_LOG": str(log)},
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    uploads = [line for line in log.read_text().splitlines() if line.startswith("release upload ")]
    assert uploads == ["release upload 9.8.7 release-dmg/OnlineWorker_9.8.7_arm64.dmg release-dmg/OnlineWorker_9.8.7_x86_64.dmg --clobber"]
