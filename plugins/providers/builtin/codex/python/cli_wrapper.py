from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Sequence

default_data_dir = None
load_config = None
set_data_dir = None
AppState = None
AppServerProcess = None
ensure_codex_remote_message_proxy = None


def _ensure_runtime_dependencies() -> None:
    global AppServerProcess
    global AppState
    global default_data_dir
    global ensure_codex_remote_message_proxy
    global load_config
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

    if AppServerProcess is None:
        from plugins.providers.builtin.codex.python.process import (
            AppServerProcess as imported_app_server_process,
        )

        AppServerProcess = imported_app_server_process

    if ensure_codex_remote_message_proxy is None:
        from plugins.providers.builtin.codex.python.remote_proxy import (
            ensure_codex_remote_message_proxy as imported_ensure_remote_proxy,
        )

        ensure_codex_remote_message_proxy = imported_ensure_remote_proxy


def _contains_remote_arg(args: Sequence[str]) -> bool:
    for arg in args:
        if arg == "--remote" or arg.startswith("--remote="):
            return True
    return False


def build_codex_remote_argv(
    codex_bin: str,
    remote_url: str,
    passthrough_args: Sequence[str],
) -> list[str]:
    if _contains_remote_arg(passthrough_args):
        raise ValueError("ow-codex 管理 --remote 参数；请不要手动传入 --remote。")
    return [
        str(codex_bin or "codex"),
        "--remote",
        str(remote_url),
        *[str(arg) for arg in passthrough_args],
    ]


async def run_codex_child(argv: Sequence[str]) -> int:
    proc = await asyncio.create_subprocess_exec(*argv)
    return await proc.wait()


def _codex_tool_config(config):
    get_provider = getattr(config, "get_provider", None)
    if callable(get_provider):
        provider = get_provider("codex")
        if provider is not None:
            return provider
    providers = getattr(config, "providers", None)
    if isinstance(providers, dict):
        provider = providers.get("codex")
        if provider is not None:
            return provider
    return None


async def run_ow_codex_once(
    passthrough_args: Sequence[str],
    *,
    data_dir: str | None = None,
) -> int:
    _ensure_runtime_dependencies()
    resolved_data_dir = data_dir or default_data_dir()
    set_data_dir(resolved_data_dir)
    config = load_config(data_dir=resolved_data_dir)
    state = AppState(config=config)

    tool_cfg = _codex_tool_config(config)
    codex_bin = str(getattr(tool_cfg, "codex_bin", "") or "codex")
    app_server_port = int(getattr(tool_cfg, "app_server_port", 0) or 0)

    app_server = AppServerProcess(codex_bin=codex_bin, port=app_server_port, protocol="ws")
    upstream_url = await app_server.start()
    try:
        proxy_url = await ensure_codex_remote_message_proxy(state, upstream_url)
        argv = build_codex_remote_argv(codex_bin, proxy_url, passthrough_args)
        return await run_codex_child(argv)
    finally:
        runtime = state.get_provider_runtime("codex")
        proxy = runtime.remote_proxy
        if proxy is not None:
            await proxy.stop()
            runtime.remote_proxy = None
        await app_server.stop()


def build_ow_codex_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ow-codex",
        description="Run Codex CLI through OnlineWorker's local message rewrite proxy.",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="OnlineWorker data dir; defaults to the installed app data dir.",
    )
    parser.add_argument(
        "codex_args",
        nargs=argparse.REMAINDER,
        help="Arguments forwarded to codex after the managed --remote option.",
    )
    return parser


def parse_ow_codex_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = build_ow_codex_parser()
    raw_args = list(sys.argv[1:] if argv is None else argv)
    data_dir: str | None = None
    codex_args: list[str] = []

    index = 0
    while index < len(raw_args):
        arg = raw_args[index]
        if arg == "--":
            codex_args.extend(raw_args[index + 1 :])
            break
        if arg in ("-h", "--help"):
            parser.print_help()
            raise SystemExit(0)
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

        codex_args.extend(raw_args[index:])
        break

    return argparse.Namespace(data_dir=data_dir, codex_args=codex_args)


async def run_ow_codex_from_args(args: argparse.Namespace) -> int:
    return await run_ow_codex_once(args.codex_args, data_dir=args.data_dir)


async def _main(argv: Sequence[str] | None = None) -> int:
    args = parse_ow_codex_args(argv)
    return await run_ow_codex_from_args(args)


def main() -> int:
    return asyncio.run(_main())
