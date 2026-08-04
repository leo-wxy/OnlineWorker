from __future__ import annotations

import asyncio
import importlib
import os
import signal
import tempfile
from collections.abc import Mapping, Sequence

from .contracts import AiServiceConfig


async def run_cli_completion(
    *,
    argv: Sequence[str],
    prompt: str,
    timeout_seconds: float,
    env: Mapping[str, str] | None = None,
) -> str:
    normalized_argv = [str(part) for part in argv if part is not None]
    if not normalized_argv:
        raise ValueError("Provider login completion command is empty")

    with tempfile.TemporaryDirectory(prefix="onlineworker-ai-") as cwd:
        process = await asyncio.create_subprocess_exec(
            *normalized_argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=dict(env) if env is not None else None,
            start_new_session=True,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(str(prompt or "").encode("utf-8")),
                timeout=max(0.01, float(timeout_seconds)),
            )
        except asyncio.TimeoutError:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                process.kill()
            await process.wait()
            raise TimeoutError(
                f"Provider login completion timed out after {timeout_seconds}s"
            ) from None

    stdout_text = (stdout or b"").decode("utf-8", errors="replace").strip()
    stderr_text = (stderr or b"").decode("utf-8", errors="replace").strip()
    if process.returncode != 0:
        detail = stderr_text or stdout_text or "no process output"
        raise RuntimeError(
            f"Provider login completion failed with exit code {process.returncode}: "
            f"{detail[-1000:]}"
        )
    if not stdout_text:
        raise RuntimeError("Provider login completion returned empty stdout")
    return stdout_text


async def complete_with_provider_login(
    *,
    service: AiServiceConfig,
    model: str,
    prompt: str,
    timeout_seconds: int,
):
    entrypoint = service.completion_entrypoint
    if not entrypoint:
        raise ValueError(
            f"AI service {service.id!r} has no provider login completion entrypoint"
        )

    module_name, separator, function_name = entrypoint.partition(":")
    if not separator or not module_name or not function_name:
        raise ValueError(
            f"Invalid provider login completion entrypoint: {entrypoint!r}"
        )

    module = importlib.import_module(module_name)
    completion = getattr(module, function_name)
    text = await completion(
        service=service,
        model=model,
        prompt=prompt,
        timeout_seconds=timeout_seconds,
    )
    normalized = str(text or "").strip()
    if not normalized:
        raise RuntimeError(
            f"Provider login completion returned no text: {service.owner_provider_id or service.id}"
        )

    from .client import AiHttpResponse

    return AiHttpResponse(
        text=normalized,
        raw={"provider_id": service.owner_provider_id},
    )
