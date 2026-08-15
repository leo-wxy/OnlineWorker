from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest

from core.ai.contracts import AiServiceConfig
from core.ai.provider_login import complete_with_provider_login, run_cli_completion
from plugins.providers.builtin.claude.python.adapter import ClaudeAdapter
from plugins.providers.builtin.claude.python.ai_completion import (
    build_login_env as build_claude_login_env,
    build_completion_argv as build_claude_completion_argv,
)
from plugins.providers.builtin.codex.python.ai_completion import (
    build_login_env as build_codex_login_env,
    build_completion_argv as build_codex_completion_argv,
)


@pytest.mark.asyncio
async def test_run_cli_completion_passes_prompt_through_stdin_without_session_state():
    text = await run_cli_completion(
        argv=[
            sys.executable,
            "-c",
            "import json, sys; print(json.dumps({'prompt': sys.stdin.read()}))",
        ],
        prompt="生成摘要",
        timeout_seconds=2,
    )

    assert text == '{"prompt": "\\u751f\\u6210\\u6458\\u8981"}'


@pytest.mark.asyncio
async def test_run_cli_completion_kills_timed_out_process():
    with pytest.raises(TimeoutError, match="timed out"):
        await run_cli_completion(
            argv=[
                sys.executable,
                "-c",
                "import time; time.sleep(2)",
            ],
            prompt="生成摘要",
            timeout_seconds=0.05,
        )


@pytest.mark.asyncio
async def test_run_cli_completion_kills_timed_out_child_process_group(tmp_path):
    marker = tmp_path / "child-survived"
    child_code = (
        "import pathlib, time; "
        "time.sleep(0.2); "
        f"pathlib.Path({str(marker)!r}).write_text('alive')"
    )
    parent_code = (
        "import subprocess, sys, time; "
        f"subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
        "time.sleep(2)"
    )

    with pytest.raises(TimeoutError, match="timed out"):
        await run_cli_completion(
            argv=[sys.executable, "-c", parent_code],
            prompt="生成摘要",
            timeout_seconds=0.05,
        )
    await asyncio.sleep(0.35)

    assert marker.exists() is False


@pytest.mark.asyncio
async def test_provider_login_completion_loads_plugin_entrypoint(monkeypatch):
    calls: list[dict] = []

    async def fake_complete(**kwargs):
        calls.append(kwargs)
        return '{"preview_title": "插件摘要", "summary": "已调用插件登录态入口。"}'

    monkeypatch.setattr(
        "core.ai.provider_login.importlib.import_module",
        lambda module_name: (
            SimpleNamespace(complete=fake_complete)
            if module_name == "example.ai_completion"
            else None
        ),
    )
    service = AiServiceConfig(
        id="example_login",
        protocol="provider_login",
        owner_provider_id="example",
        completion_entrypoint="example.ai_completion:complete",
        enabled=True,
    )

    response = await complete_with_provider_login(
        service=service,
        model="",
        prompt="生成摘要",
        timeout_seconds=9,
    )

    assert response.text == '{"preview_title": "插件摘要", "summary": "已调用插件登录态入口。"}'
    assert response.raw == {"provider_id": "example"}
    assert calls[0]["prompt"] == "生成摘要"
    assert calls[0]["timeout_seconds"] == 9


@pytest.mark.asyncio
async def test_claude_login_readiness_has_a_timeout(monkeypatch):
    class SlowProcess:
        pid = 999999
        returncode = None

        def __init__(self):
            self.killed = False

        async def communicate(self):
            await asyncio.sleep(2)
            return b"", b""

        def kill(self):
            self.killed = True
            self.returncode = -9

        async def wait(self):
            return self.returncode

    process = SlowProcess()
    monkeypatch.setattr(
        "plugins.providers.builtin.claude.python.adapter.asyncio.create_subprocess_exec",
        lambda *args, **kwargs: asyncio.sleep(0, result=process),
    )
    adapter = ClaudeAdapter()

    readiness = await adapter._check_cli_readiness_for_prefix(
        ["claude"],
        env={},
        timeout_seconds=0.05,
    )

    assert readiness["ready"] is False
    assert readiness["reason"] == "authStatusFailed"
    assert "timed out" in readiness["detail"]
    assert process.killed is True


def test_provider_login_environments_drop_api_credentials(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "api-key")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-key")
    monkeypatch.setenv("CODEX_API_KEY", "codex-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-key")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "anthropic-token")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.example.test")
    monkeypatch.setenv("CODEX_HOME", "/tmp/example-codex-home")

    codex_env = build_codex_login_env()
    claude_env = build_claude_login_env(ClaudeAdapter())

    assert "OPENAI_API_KEY" not in codex_env
    assert "AZURE_OPENAI_API_KEY" not in codex_env
    assert "CODEX_API_KEY" not in codex_env
    assert codex_env["CODEX_HOME"] == "/tmp/example-codex-home"
    assert all(not key.startswith("ANTHROPIC_") for key in claude_env)


def test_codex_login_completion_is_ephemeral_and_read_only():
    argv = build_codex_completion_argv("/opt/example/bin/codex", "gpt-example")

    assert argv[0:2] == ["/opt/example/bin/codex", "exec"]
    assert argv[argv.index("--disable") + 1] == "hooks"
    assert "--ephemeral" in argv
    assert "--ignore-user-config" in argv
    assert "--skip-git-repo-check" in argv
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    assert argv[argv.index("--model") + 1] == "gpt-example"
    assert argv[-1] == "-"


def test_claude_login_completion_disables_tools_and_session_persistence():
    argv = build_claude_completion_argv(
        ["/opt/example/bin/claude"],
        "claude-example",
    )

    assert argv[0:2] == ["/opt/example/bin/claude", "-p"]
    assert "--safe-mode" in argv
    assert "--no-session-persistence" in argv
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    assert argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("--model") + 1] == "claude-example"
