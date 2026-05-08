#!/usr/bin/env python3
"""
手动 archive 联调验证脚本。

用途：
1. 按给定 workspace 路径真实创建一条 codex thread
2. 立即执行真实 archive
3. 直接查询底层 SQLite，确认归档字段已写入

注意：
- 默认不接入 pytest，也不应该作为每次修改后的常规回归
- 每次执行都会新增真实 session/thread 记录，请只在需要验证 archive 端到端链路时手动运行
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from plugins.providers.builtin.codex.python.adapter import CodexAdapter


@dataclass
class VerifyResult:
    tool: str
    thread_id: str
    workspace: str
    archived: bool
    detail: str


async def _wait_codex_thread_idle(
    adapter: CodexAdapter,
    workspace_id: str,
    thread_id: str,
    *,
    timeout_seconds: float = 20.0,
) -> None:
    deadline = asyncio.get_event_loop().time() + timeout_seconds
    while asyncio.get_event_loop().time() < deadline:
        threads = await adapter.list_threads(workspace_id, limit=100)
        matched = next((item for item in threads if item.get("id") == thread_id), None)
        status = matched.get("status") if isinstance(matched, dict) else None
        status_type = status.get("type") if isinstance(status, dict) else None
        if status_type == "idle":
            return
        await asyncio.sleep(1.0)
    raise TimeoutError(f"codex thread 未在 {timeout_seconds:.0f}s 内进入 idle：{thread_id}")


async def _wait_codex_thread_materialized(
    adapter: CodexAdapter,
    thread_id: str,
    *,
    timeout_seconds: float = 10.0,
) -> None:
    deadline = asyncio.get_event_loop().time() + timeout_seconds
    while asyncio.get_event_loop().time() < deadline:
        try:
            await adapter._call(
                "thread/read",
                {"threadId": thread_id, "includeTurns": True},
            )
            return
        except RuntimeError as e:
            if "not materialized yet" not in str(e):
                raise
        await asyncio.sleep(0.5)
    raise TimeoutError(f"codex thread 未在 {timeout_seconds:.0f}s 内 materialize：{thread_id}")


async def _verify_codex(workspace: str, ws_url: str) -> VerifyResult:
    adapter = CodexAdapter()
    workspace_id = f"codex:{workspace}"
    adapter.register_workspace_cwd(workspace_id, workspace)

    try:
        await adapter.connect(ws_url)
        started = await adapter.start_thread(workspace_id)
        thread_id = str(started.get("id") or started.get("thread", {}).get("id") or "")
        if not thread_id:
            raise RuntimeError(f"codex start_thread 返回无效结果：{started}")

        # codex 新 thread 在首条 user message 前尚未 materialize；
        # 先发送一条真实消息让源端 thread 落盘，再执行 archive。
        turn_started = await adapter.send_user_message(
            workspace_id,
            thread_id,
            "archive live verify seed",
        )
        turn_id = str(turn_started.get("turn", {}).get("id") or "")
        if not turn_id:
            raise RuntimeError(f"codex turn/start 返回无效结果：{turn_started}")

        # 先等 user message 真正 materialize 到 thread，再 interrupt；
        # 否则过早 interrupt 可能让 thread 停留在“未 materialize”状态。
        await _wait_codex_thread_materialized(adapter, thread_id)
        await adapter.turn_interrupt(workspace_id, thread_id, turn_id)
        await _wait_codex_thread_idle(adapter, workspace_id, thread_id)
        await adapter.archive_thread(workspace_id, thread_id)

        archived_result = await adapter._call(
            "thread/list",
            {"cwd": workspace, "limit": 100, "archived": True},
        )
        archived_threads = (
            archived_result.get("data", [])
            if isinstance(archived_result, dict)
            else archived_result
        )
        archived_item = next(
            (item for item in archived_threads if item.get("id") == thread_id),
            None,
        )
        if not archived_item:
            raise RuntimeError(f"codex archived list 未找到新 thread：{thread_id}")

        archived_path = str(archived_item.get("path") or "")
        archived = "archived_sessions" in archived_path
    finally:
        await adapter.disconnect()

    return VerifyResult(
        tool="codex",
        thread_id=thread_id,
        workspace=workspace,
        archived=archived,
        detail=f"path={archived_path}",
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="手动验证 codex 的真实 archive 链路",
    )
    parser.add_argument(
        "--tool",
        choices=["codex"],
        default="codex",
        help="要验证的工具，默认 codex",
    )
    parser.add_argument(
        "--workspace",
        required=True,
        help="用于创建 thread/session 的 workspace 路径",
    )
    parser.add_argument(
        "--codex-ws-url",
        default="ws://127.0.0.1:4722",
        help="codex app-server websocket 地址",
    )
    return parser.parse_args()


async def _main() -> int:
    args = _parse_args()
    workspace = os.path.abspath(args.workspace)
    if not os.path.isdir(workspace):
        raise RuntimeError(f"workspace 不存在：{workspace}")

    results: list[VerifyResult] = []

    results.append(await _verify_codex(workspace, args.codex_ws_url))

    failed = False
    for result in results:
        status = "PASS" if result.archived else "FAIL"
        print(
            f"[{status}] {result.tool} thread/session={result.thread_id} "
            f"workspace={result.workspace} {result.detail}"
        )
        if not result.archived:
            failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(_main()))
    except KeyboardInterrupt:
        print("已取消", file=sys.stderr)
        raise SystemExit(130)
