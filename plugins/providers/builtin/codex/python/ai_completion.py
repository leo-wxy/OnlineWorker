from __future__ import annotations

from config import get_data_dir, load_provider_runtime_config
from core.ai.provider_login import run_cli_completion
from plugins.providers.builtin.codex.python.process import _build_subprocess_env


def build_login_env() -> dict[str, str]:
    env = _build_subprocess_env()
    for key in tuple(env):
        normalized = key.upper()
        if (
            normalized.startswith("OPENAI_")
            or normalized.startswith("AZURE_OPENAI_")
            or normalized == "CODEX_API_KEY"
        ):
            env.pop(key, None)
    return env


def build_completion_argv(codex_bin: str, model: str = "") -> list[str]:
    argv = [
        str(codex_bin or "codex"),
        "exec",
        "--disable",
        "hooks",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--color",
        "never",
    ]
    if str(model or "").strip():
        argv.extend(["--model", str(model).strip()])
    argv.append("-")
    return argv


async def complete(*, service, model: str, prompt: str, timeout_seconds: int) -> str:
    runtime_config = load_provider_runtime_config("codex", data_dir=get_data_dir())
    provider = runtime_config.get_provider("codex")
    codex_bin = str(getattr(provider, "bin", "") or "codex")
    return await run_cli_completion(
        argv=build_completion_argv(codex_bin, model),
        prompt=prompt,
        timeout_seconds=timeout_seconds,
        env=build_login_env(),
    )
