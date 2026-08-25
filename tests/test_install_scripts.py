import os
from pathlib import Path
import subprocess

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "script_name",
    ("install-current-dmg.sh", "restart-installed-app.sh"),
)
def test_runtime_script_refuses_to_stop_its_own_onlineworker_parent(
    tmp_path: Path,
    script_name: str,
):
    fake_ps = tmp_path / "ps"
    fake_ps.write_text(
        "#!/bin/bash\n"
        "echo '1 /Applications/OnlineWorker.app/Contents/MacOS/onlineworker-bot "
        "--data-dir /tmp/OnlineWorker'\n",
        encoding="utf-8",
    )
    fake_ps.chmod(0o755)
    script = PROJECT_ROOT / "scripts" / script_name
    missing_target = tmp_path / "missing"
    env = os.environ.copy()
    env["PATH"] = f"{tmp_path}:{env['PATH']}"

    result = subprocess.run(
        ["/bin/bash", str(script), str(missing_target)],
        capture_output=True,
        env=env,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "inside its own process tree" in result.stdout


def test_restart_force_stops_runtime_that_ignores_term(tmp_path: Path):
    state_file = tmp_path / "state"
    state_file.write_text("old", encoding="utf-8")
    kill_log = tmp_path / "kill.log"

    fake_ps = tmp_path / "ps"
    fake_ps.write_text(
        "#!/bin/bash\n"
        "if [ \"$1\" = '-ww' ]; then\n"
        "  echo '1 /Applications/ChatGPT.app/Contents/Resources/codex'\n"
        "elif [ \"$(cat \"$OW_TEST_STATE\")\" = 'old' ]; then\n"
        "  echo '15310 1 00:00 /Applications/OnlineWorker.app/Contents/MacOS/onlineworker-bot --data-dir /tmp/OnlineWorker'\n"
        "  echo '15408 15310 00:00 /Applications/OnlineWorker.app/Contents/MacOS/onlineworker-bot --data-dir /tmp/OnlineWorker'\n"
        "elif [ \"$(cat \"$OW_TEST_STATE\")\" = 'started' ]; then\n"
        "  echo '20001 1 00:00 /Applications/OnlineWorker.app/Contents/MacOS/onlineworker-app'\n"
        "  echo '20002 20001 00:00 /Applications/OnlineWorker.app/Contents/MacOS/onlineworker-bot --data-dir /tmp/OnlineWorker'\n"
        "fi\n",
        encoding="utf-8",
    )
    fake_ps.chmod(0o755)

    fake_open = tmp_path / "open"
    fake_open.write_text(
        "#!/bin/bash\n"
        "echo started > \"$OW_TEST_STATE\"\n",
        encoding="utf-8",
    )
    fake_open.chmod(0o755)

    bash_env = tmp_path / "bash-env"
    bash_env.write_text(
        "kill() {\n"
        "  echo \"$*\" >> \"$OW_TEST_KILL_LOG\"\n"
        "  if [ \"$1\" = '-KILL' ]; then echo stopped > \"$OW_TEST_STATE\"; fi\n"
        "}\n"
        "sleep() { SECONDS=$((SECONDS + 1)); }\n",
        encoding="utf-8",
    )

    app_path = tmp_path / "OnlineWorker.app"
    app_path.mkdir()
    env = os.environ.copy()
    env.update(
        {
            "BASH_ENV": str(bash_env),
            "OW_TEST_KILL_LOG": str(kill_log),
            "OW_TEST_STATE": str(state_file),
            "PATH": f"{tmp_path}:{env['PATH']}",
        }
    )

    result = subprocess.run(
        [
            "/bin/bash",
            str(PROJECT_ROOT / "scripts" / "restart-installed-app.sh"),
            str(app_path),
        ],
        capture_output=True,
        env=env,
        text=True,
        check=False,
        timeout=5,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert kill_log.read_text(encoding="utf-8").splitlines() == [
        "15310 15408",
        "-KILL 15310 15408",
    ]
