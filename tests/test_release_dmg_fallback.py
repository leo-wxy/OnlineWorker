import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FALLBACK_SCRIPT = ROOT / "scripts" / "create-dmg-from-app.sh"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release-dmg.yml"


def test_release_workflow_falls_back_only_after_the_normal_build_fails():
    workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    assert "if bash scripts/build.sh; then" in workflow
    assert "bash scripts/create-dmg-from-app.sh" in workflow


def test_headless_dmg_fallback_packages_an_existing_app_bundle(tmp_path):
    app_bundle = tmp_path / "OnlineWorker.app"
    executable = app_bundle / "Contents" / "MacOS" / "onlineworker-app"
    executable.parent.mkdir(parents=True)
    executable.write_text("binary", encoding="utf-8")
    executable.chmod(0o755)
    sidecar = app_bundle / "Contents" / "MacOS" / "onlineworker-bot"
    sidecar.write_text("sidecar", encoding="utf-8")
    sidecar.chmod(0o755)

    output_dir = tmp_path / "output"
    fake_ditto = tmp_path / "ditto"
    fake_ditto.write_text(
        "#!/bin/bash\nset -euo pipefail\ncp -R \"$1\" \"$2\"\n",
        encoding="utf-8",
    )
    fake_ditto.chmod(0o755)

    fake_hdiutil = tmp_path / "hdiutil"
    fake_hdiutil.write_text(
        "#!/bin/bash\nset -euo pipefail\noutput=\"${@: -1}\"\n"
        "test -L \"${5}/Applications\"\nmkdir -p \"$(dirname \"$output\")\"\n"
        "printf dmg > \"$output\"\n",
        encoding="utf-8",
    )
    fake_hdiutil.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "ONLINEWORKER_APP_BUNDLE_PATH": str(app_bundle),
            "ONLINEWORKER_DMG_OUTPUT_DIR": str(output_dir),
            "ONLINEWORKER_DMG_ARCH": "aarch64",
            "DITTO_BIN": str(fake_ditto),
            "HDIUTIL_BIN": str(fake_hdiutil),
        }
    )

    result = subprocess.run(
        ["bash", str(FALLBACK_SCRIPT)],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert (output_dir / f"OnlineWorker_{version}_aarch64.dmg").read_text() == "dmg"
