#!/usr/bin/env python3
import argparse
import asyncio

from plugins.providers.builtin.codex.python.tui_host_runtime import CodexTuiHost, resolve_host_thread_id


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a single-owner Codex TUI host wrapper.")
    parser.add_argument("--data-dir", required=True, help="OnlineWorker data dir")
    parser.add_argument("--remote", help="Optional remote codex app-server ws url")
    parser.add_argument("--cd", required=True, help="Workspace cwd for codex resume")
    parser.add_argument("--codex-bin", default="codex", help="Codex executable path")
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
    return parser.parse_args()


async def _main() -> int:
    args = parse_args()
    target = (args.target or "").strip()
    explicit_thread_id = target or None
    explicit_topic_id = None
    if target.isdigit():
        explicit_topic_id = int(target)
        explicit_thread_id = None

    thread_id = resolve_host_thread_id(
        cwd=args.cd,
        data_dir=args.data_dir,
        thread_id=explicit_thread_id,
        topic_id=explicit_topic_id,
    )
    host = CodexTuiHost(
        data_dir=args.data_dir,
        thread_id=thread_id,
        cwd=args.cd,
        remote_url=args.remote,
        codex_bin=args.codex_bin,
        extra_args=args.extra_arg,
    )
    return await host.run()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
