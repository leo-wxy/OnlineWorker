from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path


def _load_smoke_module():
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "scripts" / "claude_readiness_smoke.py"
    spec = importlib.util.spec_from_file_location("claude_readiness_smoke", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_claude_readiness_smoke_sanitizes_secret_like_fields():
    module = _load_smoke_module()

    readiness = module.sanitize_readiness(
        {
            "ready": True,
            "source": "runtimeEnv",
            "reason": "ok",
            "authMethod": "authTokenEnv",
            "checked_at": 1000.0,
            "detail": "Claude provider is ready.",
            "ANTHROPIC_AUTH_TOKEN": "secret-token",
            "raw": {"token": "secret-token"},
        }
    )

    assert readiness == {
        "ready": True,
        "source": "runtimeEnv",
        "reason": "ok",
        "authMethod": "authTokenEnv",
        "checked_at": 1000.0,
        "detail": "Claude provider is ready.",
    }


def test_claude_readiness_smoke_script_prints_sanitized_mock_result(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL"):
        env.pop(key, None)
    fake_claude = tmp_path / "fake-claude"
    fake_claude.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"auth\" ] && [ \"$2\" = \"status\" ]; then\n"
        "  printf '%s\\n' '{\"loggedIn\":false,\"authMethod\":\"none\",\"apiProvider\":\"firstParty\"}'\n"
        "  exit 0\n"
        "fi\n"
        "exit 64\n",
        encoding="utf-8",
    )
    fake_claude.chmod(0o755)

    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "claude_readiness_smoke.py"),
            "--claude-bin",
            str(fake_claude),
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=repo_root,
        env=env,
    )

    payload = json.loads(result.stdout)

    assert payload["provider"] == "claude"
    assert payload["readiness"]["ready"] is False
    assert payload["readiness"]["reason"] == "loggedOut"
    assert payload["readiness"]["authMethod"] == "none"
    methods = {method["id"]: method for method in payload["methods"]}
    assert methods["configured_cli"]["selected"] is True
    assert methods["configured_cli"]["detected"] is True
    assert methods["configured_cli"]["available"] is False
    assert methods["configured_cli"]["reason"] == "loggedOut"
    assert methods["runtime_env"]["selected"] is False
    assert methods["runtime_env"]["detected"] is False
    assert methods["runtime_env"]["available"] is False
    assert methods["ow_claude_wrapper"]["detected"] is True
    assert methods["ow_claude_wrapper"]["available"] is False
    assert methods["ow_claude_wrapper"]["selected"] is False
    assert "ANTHROPIC_AUTH_TOKEN" not in result.stdout


def test_claude_readiness_smoke_uses_explicit_config_bin(tmp_path):
    module = _load_smoke_module()
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
schema_version: 2
providers:
  claude:
    bin: /tmp/custom-claude
""",
        encoding="utf-8",
    )
    args = type("Args", (), {
        "claude_bin": None,
        "config": str(config_path),
        "data_dir": None,
    })()

    configured_bin, source = module.resolve_configured_claude_bin(args)

    assert configured_bin == "/tmp/custom-claude"
    assert source == str(config_path)


def test_claude_readiness_smoke_uses_explicit_launch_methods_from_config(tmp_path):
    module = _load_smoke_module()
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
schema_version: 2
providers:
  claude:
    bin: claude
    launch_methods:
      - id: native
        label: Native Claude
        bin: claude
      - id: raven
        label: Raven Claude
        bin: /Users/example/.nvm/versions/node/v20.20.1/bin/raven cc
""",
        encoding="utf-8",
    )
    args = type("Args", (), {
        "claude_bin": None,
        "config": str(config_path),
        "data_dir": None,
    })()

    configured_bin, launch_methods, source = module.resolve_configured_claude_config(args)

    assert configured_bin == "claude"
    assert source == str(config_path)
    assert launch_methods == [
        {"id": "native", "label": "Native Claude", "bin": "claude"},
        {
            "id": "raven",
            "label": "Raven Claude",
            "bin": "/Users/example/.nvm/versions/node/v20.20.1/bin/raven cc",
        },
    ]


def test_claude_readiness_smoke_script_reports_configured_launch_methods(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL"):
        env.pop(key, None)

    native = tmp_path / "native-claude"
    native.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"auth\" ] && [ \"$2\" = \"status\" ]; then\n"
        "  printf '%s\\n' '{\"loggedIn\":false,\"authMethod\":\"none\",\"apiProvider\":\"firstParty\"}'\n"
        "  exit 0\n"
        "fi\n"
        "exit 64\n",
        encoding="utf-8",
    )
    native.chmod(0o755)
    raven = tmp_path / "raven"
    raven.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"cc\" ] && [ \"$2\" = \"auth\" ] && [ \"$3\" = \"status\" ]; then\n"
        "  printf '%s\\n' '{\"loggedIn\":true,\"authMethod\":\"oauth_token\",\"apiProvider\":\"firstParty\"}'\n"
        "  exit 0\n"
        "fi\n"
        "exit 64\n",
        encoding="utf-8",
    )
    raven.chmod(0o755)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
schema_version: 2
providers:
  claude:
    bin: "{native}"
    launch_methods:
      - id: native
        label: Native Claude
        bin: "{native}"
      - id: raven
        label: Raven Claude
        bin: "{raven} cc"
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "claude_readiness_smoke.py"),
            "--config",
            str(config_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=repo_root,
        env=env,
    )

    payload = json.loads(result.stdout)
    assert payload["readiness"]["ready"] is True
    assert payload["readiness"]["launchMethod"]["id"] == "raven"
    methods = {method["id"]: method for method in payload["methods"]}
    assert methods["native"]["selected"] is False
    assert methods["native"]["ready"] is False
    assert methods["raven"]["selected"] is True
    assert methods["raven"]["ready"] is True
    assert "ANTHROPIC_AUTH_TOKEN" not in result.stdout


def test_claude_readiness_smoke_fail_on_unavailable_exits_nonzero(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL"):
        env.pop(key, None)
    fake_claude = tmp_path / "fake-claude"
    fake_claude.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' '{\"loggedIn\":false,\"authMethod\":\"none\"}'\n",
        encoding="utf-8",
    )
    fake_claude.chmod(0o755)

    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "claude_readiness_smoke.py"),
            "--claude-bin",
            str(fake_claude),
            "--fail-on-unavailable",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=repo_root,
        env=env,
    )

    assert result.returncode == 2
    assert '"ready": false' in result.stdout
