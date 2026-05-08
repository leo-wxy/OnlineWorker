#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
MAIN_PY = REPO_ROOT / "main.py"
PROJECT_PYTHON = Path("/Users/wxy/.pyenv/versions/3.13.1/bin/python3")

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from plugins.providers.builtin.claude.python.adapter import ClaudeAdapter
from plugins.providers.builtin.claude.python.adapter import resolve_claude_bin


def _print(message: str) -> None:
    print(message, flush=True)


def _default_env_file() -> str:
    return str(Path.home() / "Library/Application Support/OnlineWorker/.env")


def _load_runtime_env(env_file: str | None) -> None:
    if not env_file:
        return
    path = Path(env_file)
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key.strip()] = value.strip()


def _make_data_dir(prefix: str) -> Path:
    return Path(tempfile.gettempdir()) / f"{prefix}-{uuid.uuid4().hex[:8]}"


def _insert_cli_options_before_prompt(argv: list[str], extra: list[str]) -> list[str]:
    if not argv:
        return extra
    return [*argv[:-1], *extra, argv[-1]]


def build_permission_smoke_plan(
    target: Path,
    content: str,
    allow_always: bool,
) -> dict[str, Any]:
    runs = [
        {
            "label": "first",
            "target": target,
            "content": content,
        }
    ]
    if allow_always:
        second_suffix = target.suffix or ".txt"
        second_target = target.with_name(f"{target.stem}_allow_always{second_suffix}")
        runs.append(
            {
                "label": "second",
                "target": second_target,
                "content": f"{content} [allow-always-second-run]",
            }
        )
    return {
        "expected_approvals": 1,
        "runs": runs,
    }


def _build_bash_write_prompt(target: Path, content: str) -> str:
    return (
        "Use the Bash tool exactly once to run the following command, then reply with exactly OK:\n"
        f"printf '%s' {json.dumps(content)} > {json.dumps(str(target))}"
    )


async def _run_single_claude_prompt(
    adapter: ClaudeAdapter,
    session_id: str,
    prompt: str,
    timeout: int,
) -> dict[str, Any]:
    argv = _insert_cli_options_before_prompt(
        adapter._build_send_argv(session_id, prompt),
        ["--tools=Bash"],
    )
    _print(f"[run] {' '.join(argv)}")

    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(REPO_ROOT),
        env=adapter._build_claude_env(),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        stdout, stderr = await proc.communicate()
        raise RuntimeError(
            "Claude CLI 超时："
            f"stdout={stdout.decode('utf-8', errors='ignore')} "
            f"stderr={stderr.decode('utf-8', errors='ignore')}"
        )

    return {
        "argv": argv,
        "returncode": proc.returncode,
        "stdout": stdout.decode("utf-8", errors="ignore"),
        "stderr": stderr.decode("utf-8", errors="ignore"),
    }


async def _bridge_roundtrip(data_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    bridge_python = str(PROJECT_PYTHON if PROJECT_PYTHON.exists() else Path(sys.executable))
    proc = await asyncio.create_subprocess_exec(
        bridge_python,
        str(MAIN_PY),
        "--claude-hook-bridge",
        "--data-dir",
        str(data_dir),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(REPO_ROOT),
    )
    raw_stdout, raw_stderr = await proc.communicate(
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "hook bridge 执行失败："
            f"returncode={proc.returncode} stderr={raw_stderr.decode('utf-8', errors='ignore')}"
        )
    raw_text = raw_stdout.decode("utf-8", errors="ignore").strip() or "{}"
    return json.loads(raw_text)


def _extract_event_method(params: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    message = params.get("message") or {}
    return str(message.get("method") or ""), message.get("params") or {}


async def run_permission_write_downloads(args: argparse.Namespace) -> int:
    _load_runtime_env(args.env_file)

    target = Path(args.target) if args.target else (
        Path.home() / "Downloads" / f"onlineworker_claude_hook_smoke_{int(time.time())}.txt"
    )
    plan = build_permission_smoke_plan(
        target=target,
        content=str(args.content),
        allow_always=bool(args.allow_always),
    )
    data_dir = _make_data_dir("ow-claude-smoke")
    workspace_id = "claude:smoke"
    session_id = str(uuid.uuid4())

    approvals: list[dict[str, Any]] = []
    run_results: list[dict[str, Any]] = []

    adapter = ClaudeAdapter(claude_bin=resolve_claude_bin(args.claude_bin))

    async def on_event(method: str, params: dict[str, Any]) -> None:
        if method != "app-server-event":
            return
        event_method, event_params = _extract_event_method(params)
        if event_method != "item/commandExecution/requestApproval":
            return
        approvals.append(event_params)
        _print(
            "[approval] "
            f"tool={event_params.get('toolName')!r} command={event_params.get('command')!r}"
        )
        reply_body = {"behavior": "allow"}
        if args.allow_always:
            reply_body["scope"] = "session"
        await adapter.reply_server_request(
            params.get("workspace_id") or workspace_id,
            event_params.get("request_id"),
            reply_body,
        )

    if target.exists():
        target.unlink()
    if data_dir.exists():
        shutil.rmtree(data_dir)
    for step in plan["runs"]:
        step_target = step["target"]
        if step_target.exists():
            step_target.unlink()

    await adapter.connect()
    await adapter.start_hook_bridge(str(data_dir))
    adapter.register_workspace_cwd(workspace_id, str(REPO_ROOT))
    adapter.on_event(on_event)

    try:
        for step in plan["runs"]:
            run_result = await _run_single_claude_prompt(
                adapter=adapter,
                session_id=session_id,
                prompt=_build_bash_write_prompt(step["target"], step["content"]),
                timeout=args.timeout,
            )
            if run_result["returncode"] != 0:
                raise RuntimeError(
                    "Claude CLI 执行失败："
                    f"step={step['label']} "
                    f"returncode={run_result['returncode']} "
                    f"stdout={run_result['stdout']} "
                    f"stderr={run_result['stderr']}"
                )

            if not step["target"].exists():
                raise RuntimeError(f"目标文件未生成：step={step['label']} target={step['target']}")

            actual_content = step["target"].read_text(encoding="utf-8", errors="ignore")
            if actual_content != step["content"]:
                raise RuntimeError(
                    "文件内容不匹配："
                    f"step={step['label']} "
                    f"expected={step['content']!r} actual={actual_content!r}"
                )

            run_results.append(
                {
                    "label": step["label"],
                    "target": str(step["target"]),
                    "content": actual_content,
                }
            )

        if len(approvals) != int(plan["expected_approvals"]):
            raise RuntimeError(
                "审批次数不符合预期："
                f"expected={plan['expected_approvals']} actual={len(approvals)} "
                f"allow_always={bool(args.allow_always)}"
            )

        result = {
            "runs": run_results,
            "approvals": len(approvals),
            "expected_approvals": int(plan["expected_approvals"]),
            "allow_always": bool(args.allow_always),
        }
        _print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        await adapter.disconnect()
        shutil.rmtree(data_dir, ignore_errors=True)
        if not args.keep_file:
            for step in plan["runs"]:
                step["target"].unlink(missing_ok=True)


async def run_multiselect_bridge(args: argparse.Namespace) -> int:
    answers = [item.strip() for item in str(args.answers).split(",") if item.strip()]
    if not answers:
        raise RuntimeError("answers 不能为空")

    data_dir = _make_data_dir("ow-claude-ask")
    workspace_id = "claude:smoke"
    session_id = str(uuid.uuid4())
    question_text = "你希望我用哪些语言回复？"
    questions = [
        {
            "header": "语言偏好",
            "question": question_text,
            "options": [
                {"label": "Python", "description": "通用"},
                {"label": "Rust", "description": "系统"},
                {"label": "Go", "description": "服务端"},
            ],
            "multiSelect": True,
        }
    ]

    adapter = ClaudeAdapter(claude_bin=resolve_claude_bin(args.claude_bin))
    asked_events: list[dict[str, Any]] = []

    async def on_event(method: str, params: dict[str, Any]) -> None:
        if method != "app-server-event":
            return
        event_method, event_params = _extract_event_method(params)
        if event_method != "question/asked":
            return
        asked_events.append(event_params)
        _print(f"[question] {event_params.get('question')!r} multiple={event_params.get('multiple')}")
        await adapter.reply_question(
            str(event_params.get("questionId") or ""),
            [answers],
        )

    if data_dir.exists():
        shutil.rmtree(data_dir)

    await adapter.connect()
    await adapter.start_hook_bridge(str(data_dir))
    adapter.register_workspace_cwd(workspace_id, str(REPO_ROOT))
    adapter.on_event(on_event)

    payload = {
        "hook_event_name": "PreToolUse",
        "session_id": session_id,
        "cwd": str(REPO_ROOT),
        "tool_name": "AskUserQuestion",
        "tool_input": {
            "questions": questions,
        },
    }
    response = await _bridge_roundtrip(data_dir, payload)

    await adapter.disconnect()
    shutil.rmtree(data_dir, ignore_errors=True)

    if len(asked_events) != 1:
        raise RuntimeError(f"question/asked 事件数量异常：{len(asked_events)}")

    expected = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "updatedInput": {
                "questions": questions,
                "answers": {
                    question_text: ",".join(answers),
                },
            },
        }
    }
    if response != expected:
        raise RuntimeError(
            "多选 bridge 返回不符合预期："
            f"\nexpected={json.dumps(expected, ensure_ascii=False)}"
            f"\nactual={json.dumps(response, ensure_ascii=False)}"
        )

    _print(json.dumps(response, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Claude hook smoke tests")
    parser.add_argument(
        "--claude-bin",
        default="claude",
        help="Claude CLI binary path or command",
    )
    parser.add_argument(
        "--env-file",
        default=_default_env_file(),
        help="Environment file used for Claude auth/proxy settings",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    approval = subparsers.add_parser(
        "approval-write-downloads",
        help="Run a real Claude CLI smoke test that writes a file into ~/Downloads via Bash approval",
    )
    approval.add_argument("--target", default="", help="Target file path")
    approval.add_argument(
        "--content",
        default="onlineworker claude hook smoke test",
        help="Exact file content to write",
    )
    approval.add_argument(
        "--timeout",
        type=int,
        default=90,
        help="Claude CLI timeout in seconds",
    )
    approval.add_argument(
        "--allow-always",
        action="store_true",
        help="Reply using session-scope allow-always semantics and verify a second same-session Bash run skips approval",
    )
    approval.add_argument(
        "--keep-file",
        action="store_true",
        help="Do not delete the generated file after verification",
    )
    approval.set_defaults(func=run_permission_write_downloads)

    ask = subparsers.add_parser(
        "ask-multiselect",
        help="Run a bridge smoke test for AskUserQuestion multi-select updatedInput",
    )
    ask.add_argument(
        "--answers",
        default="Python,Rust",
        help="Comma-separated selected labels",
    )
    ask.set_defaults(func=run_multiselect_bridge)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return asyncio.run(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
