#!/usr/bin/env python3
import argparse
import asyncio

from plugins.providers.builtin.codex.python.tui_host_runtime import run_codex_tui_host_once


def build_codex_tui_host_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a single-owner Codex TUI host wrapper.")
    parser.add_argument("--data-dir", required=True, help="OnlineWorker data dir")
    parser.add_argument("--remote", help="Optional remote codex app-server ws url")
    parser.add_argument("--cd", required=True, help="Workspace cwd for codex resume")
    parser.add_argument("--bin", dest="provider_bin", default="codex", help="Provider executable path")
    parser.add_argument("--codex-bin", dest="provider_bin", help=argparse.SUPPRESS)
    parser.add_argument(
        "target",
        nargs="?",
        help="Optional topic_id (digits) or thread_id. Omit to bind the most recent codex thread for --cd.",
    )
    parser.add_argument(
        "--extra-arg",
        action="append",
        default=[],
        help="Extra arg forwarded to codex resume (repeatable)",
    )
    return parser


def parse_args() -> argparse.Namespace:
    return build_codex_tui_host_parser().parse_args()


async def run_from_args(args: argparse.Namespace) -> int:
    return await run_codex_tui_host_once(
        data_dir=args.data_dir,
        cwd=args.cd,
        remote_url=args.remote,
        provider_bin=args.provider_bin,
        extra_args=args.extra_arg,
        target=args.target,
    )


async def _main() -> int:
    args = parse_args()
    return await run_from_args(args)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
