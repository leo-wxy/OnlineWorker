from __future__ import annotations

import asyncio

from config import get_data_dir, load_provider_runtime_config
from core.ai.provider_login import run_cli_completion
from plugins.providers.builtin.claude.python.adapter import (
    ClaudeAdapter,
    ClaudeProviderUnavailable,
)


def build_login_env(adapter: ClaudeAdapter) -> dict[str, str]:
    env = adapter._build_claude_env()
    for key in tuple(env):
        if key.upper().startswith("ANTHROPIC_"):
            env.pop(key, None)
    return env


def build_completion_argv(command_prefix: list[str], model: str = "") -> list[str]:
    argv = [
        *command_prefix,
        "-p",
        "--safe-mode",
        "--no-chrome",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--permission-mode",
        "dontAsk",
        "--tools",
        "",
        "--output-format",
        "text",
    ]
    if str(model or "").strip():
        argv.extend(["--model", str(model).strip()])
    return argv


async def complete(*, service, model: str, prompt: str, timeout_seconds: int) -> str:
    runtime_config = load_provider_runtime_config("claude", data_dir=get_data_dir())
    provider = runtime_config.get_provider("claude")
    claude_bin = str(getattr(provider, "bin", "") or "claude")
    auth = dict(getattr(provider, "auth", {}) or {})
    launch_methods = list(getattr(provider, "launch_methods", []) or [])
    adapter = ClaudeAdapter(
        claude_bin=claude_bin,
        auth=auth,
        launch_methods=launch_methods,
    )
    started_at = asyncio.get_running_loop().time()
    login_env = build_login_env(adapter)
    readiness = await adapter._check_launch_methods_readiness(
        None,
        cli_env=login_env,
        timeout_seconds=timeout_seconds,
    )
    if readiness.get("ready") is not True:
        raise ClaudeProviderUnavailable(readiness)
    remaining_seconds = float(timeout_seconds) - (
        asyncio.get_running_loop().time() - started_at
    )
    if remaining_seconds <= 0:
        raise TimeoutError(
            f"Provider login completion timed out after {timeout_seconds}s"
        )
    return await run_cli_completion(
        argv=build_completion_argv(list(adapter._claude_command_prefix), model),
        prompt=prompt,
        timeout_seconds=remaining_seconds,
        env=login_env,
    )
