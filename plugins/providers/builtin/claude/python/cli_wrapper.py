from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sys
import tempfile
from typing import Mapping, Sequence


default_data_dir = None
load_config = None
set_data_dir = None
AppState = None
ClaudeHttpProxy = None
resolve_claude_command_prefix = None


def _ensure_runtime_dependencies() -> None:
    global AppState
    global ClaudeHttpProxy
    global default_data_dir
    global load_config
    global resolve_claude_command_prefix
    global set_data_dir

    if default_data_dir is None or load_config is None or set_data_dir is None:
        from config import (
            default_data_dir as imported_default_data_dir,
            load_config as imported_load_config,
            set_data_dir as imported_set_data_dir,
        )

        if default_data_dir is None:
            default_data_dir = imported_default_data_dir
        if load_config is None:
            load_config = imported_load_config
        if set_data_dir is None:
            set_data_dir = imported_set_data_dir

    if AppState is None:
        from core.state import AppState as imported_app_state

        AppState = imported_app_state

    if ClaudeHttpProxy is None:
        from plugins.providers.builtin.claude.python.http_proxy import (
            ClaudeHttpProxy as imported_claude_http_proxy,
        )

        ClaudeHttpProxy = imported_claude_http_proxy

    if resolve_claude_command_prefix is None:
        from plugins.providers.builtin.claude.python.adapter import (
            resolve_claude_command_prefix as imported_resolve_claude_command_prefix,
        )

        resolve_claude_command_prefix = imported_resolve_claude_command_prefix


def build_claude_proxy_env(
    base_env: Mapping[str, str] | None,
    proxy_base_url: str,
    *,
    upstream_base_url: str | None = None,
) -> dict[str, str]:
    env = {str(key): str(value) for key, value in dict(base_env or {}).items()}
    original_base_url = str(upstream_base_url or env.get("ANTHROPIC_BASE_URL") or "").strip()
    env["ONLINEWORKER_CLAUDE_UPSTREAM_BASE_URL"] = original_base_url
    env["ANTHROPIC_BASE_URL"] = str(proxy_base_url)
    if (
        env.get("ANTHROPIC_BASE_URL")
        and not str(env.get("ANTHROPIC_AUTH_TOKEN") or "").strip()
        and not str(env.get("ANTHROPIC_API_KEY") or "").strip()
    ):
        env["ANTHROPIC_API_KEY"] = "dummy"
    return env


def _shell_single_quote(value: str) -> str:
    return "'" + str(value).replace("'", "'\"'\"'") + "'"


def _create_claude_path_shim(
    shim_dir: str,
    *,
    proxy_base_url: str,
    upstream_base_url: str,
    real_claude_bin: str | None = None,
) -> str:
    original_path = str(os.environ.get("PATH") or "")
    real_claude = real_claude_bin or shutil.which("claude", path=original_path)
    if not real_claude:
        real_claude = "claude"
    shim_path = os.path.join(shim_dir, "claude")
    script = "\n".join(
        [
            "#!/bin/sh",
            f"export ANTHROPIC_BASE_URL={_shell_single_quote(proxy_base_url)}",
            f"export ONLINEWORKER_CLAUDE_UPSTREAM_BASE_URL={_shell_single_quote(upstream_base_url)}",
            "unset ANTHROPIC_API_KEY",
            f"exec {_shell_single_quote(real_claude)} \"$@\"",
            "",
        ]
    )
    with open(shim_path, "w", encoding="utf-8") as handle:
        handle.write(script)
    os.chmod(shim_path, 0o755)
    return shim_path


async def run_claude_child(argv: Sequence[str], env: Mapping[str, str]) -> int:
    proc = await asyncio.create_subprocess_exec(*argv, env=dict(env))
    return await proc.wait()


def _claude_tool_config(config):
    get_provider = getattr(config, "get_provider", None)
    if callable(get_provider):
        provider = get_provider("claude")
        if provider is not None:
            return provider
    providers = getattr(config, "providers", None)
    if isinstance(providers, dict):
        provider = providers.get("claude")
        if provider is not None:
            return provider
    return None


def _external_cli_value(tool_cfg, key: str, default=None):
    external_cli = getattr(tool_cfg, "external_cli", None)
    if isinstance(external_cli, dict):
        return external_cli.get(key, default)
    return default


def _truthy_config_value(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


async def run_ow_claude_once(
    passthrough_args: Sequence[str],
    *,
    data_dir: str | None = None,
    upstream_base_url: str | None = None,
    claude_bin: str | None = None,
    listen_host: str = "127.0.0.1",
    listen_port: int = 0,
    rewrite: bool = True,
    probe: bool = False,
    launcher_wraps_claude: bool = False,
) -> int:
    _ensure_runtime_dependencies()
    resolved_data_dir = data_dir or default_data_dir()
    set_data_dir(resolved_data_dir)
    config = load_config(data_dir=resolved_data_dir)
    state = AppState(config=config)

    tool_cfg = _claude_tool_config(config)
    configured_bin = str(claude_bin or getattr(tool_cfg, "codex_bin", "") or "claude")
    configured_upstream_base_url = str(upstream_base_url or "").strip()
    configured_launcher_wraps_claude = bool(
        launcher_wraps_claude
        or _truthy_config_value(_external_cli_value(tool_cfg, "launcher_wraps_claude"))
    )
    base_env = dict(os.environ)
    argv = [*resolve_claude_command_prefix(configured_bin), *[str(arg) for arg in passthrough_args]]
    upstream = str(
        configured_upstream_base_url
        or base_env.get("ONLINEWORKER_CLAUDE_UPSTREAM_BASE_URL")
        or base_env.get("ANTHROPIC_BASE_URL")
        or ""
    ).strip()

    proxy = ClaudeHttpProxy(
        state=state,
        upstream_base_url=upstream or None,
        listen_host=listen_host,
        listen_port=listen_port,
        rewrite=rewrite,
        probe=probe,
    )
    proxy_url = await proxy.start()
    try:
        env = build_claude_proxy_env(base_env, proxy_url, upstream_base_url=upstream or None)
        if configured_launcher_wraps_claude:
            with tempfile.TemporaryDirectory(prefix="ow-claude-launcher-") as shim_dir:
                _create_claude_path_shim(
                    shim_dir,
                    proxy_base_url=proxy_url,
                    upstream_base_url=upstream,
                )
                env["PATH"] = shim_dir + os.pathsep + str(env.get("PATH") or "")
                return await run_claude_child(argv, env)
        return await run_claude_child(argv, env)
    finally:
        await proxy.stop()


def build_ow_claude_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ow-claude",
        description="Run Claude CLI through OnlineWorker's local HTTP proxy.",
    )
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--claude-bin", default="claude")
    parser.add_argument("--upstream-base-url", default=None)
    parser.add_argument("--listen-host", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, default=0)
    parser.add_argument("--rewrite", dest="rewrite", action="store_true", default=True)
    parser.add_argument("--no-rewrite", dest="rewrite", action="store_false")
    parser.add_argument("--launcher-wraps-claude", action="store_true")
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("claude_args", nargs=argparse.REMAINDER)
    return parser


def parse_ow_claude_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = build_ow_claude_parser()
    raw_args = list(sys.argv[1:] if argv is None else argv)
    data_dir: str | None = None
    claude_bin = "claude"
    upstream_base_url: str | None = None
    listen_host = "127.0.0.1"
    listen_port = 0
    rewrite = True
    probe = False
    launcher_wraps_claude = False
    claude_args: list[str] = []

    index = 0
    while index < len(raw_args):
        arg = raw_args[index]
        if arg == "--":
            claude_args.extend(raw_args[index + 1 :])
            break
        if arg in ("-h", "--help"):
            parser.print_help()
            raise SystemExit(0)
        if arg == "--rewrite":
            rewrite = True
            index += 1
            continue
        if arg == "--no-rewrite":
            rewrite = False
            index += 1
            continue
        if arg == "--probe":
            probe = True
            index += 1
            continue
        if arg == "--launcher-wraps-claude":
            launcher_wraps_claude = True
            index += 1
            continue
        if arg == "--data-dir":
            if index + 1 >= len(raw_args):
                parser.error("argument --data-dir: expected one argument")
            data_dir = raw_args[index + 1]
            index += 2
            continue
        if arg.startswith("--data-dir="):
            data_dir = arg.split("=", 1)[1]
            index += 1
            continue
        if arg == "--claude-bin":
            if index + 1 >= len(raw_args):
                parser.error("argument --claude-bin: expected one argument")
            claude_bin = raw_args[index + 1]
            index += 2
            continue
        if arg.startswith("--claude-bin="):
            claude_bin = arg.split("=", 1)[1]
            index += 1
            continue
        if arg == "--upstream-base-url":
            if index + 1 >= len(raw_args):
                parser.error("argument --upstream-base-url: expected one argument")
            upstream_base_url = raw_args[index + 1]
            index += 2
            continue
        if arg.startswith("--upstream-base-url="):
            upstream_base_url = arg.split("=", 1)[1]
            index += 1
            continue
        if arg == "--listen-host":
            if index + 1 >= len(raw_args):
                parser.error("argument --listen-host: expected one argument")
            listen_host = raw_args[index + 1]
            index += 2
            continue
        if arg.startswith("--listen-host="):
            listen_host = arg.split("=", 1)[1]
            index += 1
            continue
        if arg == "--listen-port":
            if index + 1 >= len(raw_args):
                parser.error("argument --listen-port: expected one argument")
            listen_port = int(raw_args[index + 1])
            index += 2
            continue
        if arg.startswith("--listen-port="):
            listen_port = int(arg.split("=", 1)[1])
            index += 1
            continue

        claude_args.extend(raw_args[index:])
        break

    return argparse.Namespace(
        data_dir=data_dir,
        claude_bin=claude_bin,
        upstream_base_url=upstream_base_url,
        listen_host=listen_host,
        listen_port=listen_port,
        rewrite=rewrite,
        probe=probe,
        launcher_wraps_claude=launcher_wraps_claude,
        claude_args=claude_args,
    )


async def run_ow_claude_from_args(args: argparse.Namespace) -> int:
    return await run_ow_claude_once(
        args.claude_args,
        data_dir=args.data_dir,
        upstream_base_url=args.upstream_base_url,
        claude_bin=args.claude_bin,
        listen_host=args.listen_host,
        listen_port=args.listen_port,
        rewrite=args.rewrite,
        probe=args.probe,
        launcher_wraps_claude=args.launcher_wraps_claude,
    )


async def _main(argv: Sequence[str] | None = None) -> int:
    args = parse_ow_claude_args(argv)
    return await run_ow_claude_from_args(args)


def main() -> int:
    return asyncio.run(_main())
