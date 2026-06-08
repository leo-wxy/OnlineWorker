#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import json
import os
import socket
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_THREAD_ID = "019dbcd9-8d2b-7dc1-85ad-75dff569617e"
DEFAULT_CWD = "/Users/example"
DEFAULT_TEXT = "图片里面主要是什么内容"
DEFAULT_LOG_PATH = os.path.expanduser("~/Library/Application Support/OnlineWorker/onlineworker.log")
DEFAULT_SOCKET_PATH = os.path.expanduser("~/Library/Application Support/OnlineWorker/codex_owner_bridge.sock")
DEFAULT_ROLLOUT_PATH = os.path.expanduser(
    "~/.codex/sessions/2026/04/24/rollout-2026-04-24T08-17-47-019dbcd9-8d2b-7dc1-85ad-75dff569617e.jsonl"
)
DEFAULT_TIMEOUT_SECONDS = 90.0
DEFAULT_POLL_SECONDS = 1.0


@dataclass
class ProbeSummary:
    owner_bridge_response: dict[str, Any]
    effective_thread_id: str
    rollout_path: str
    user_turn_seen: bool
    image_input_seen: bool
    assistant_messages: list[str]
    topic_resolution_errors: list[str]
    elapsed_seconds: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="发送图文到 Codex session 并验证 rollout/日志")
    parser.add_argument("--thread-id", default=DEFAULT_THREAD_ID)
    parser.add_argument("--cwd", default=DEFAULT_CWD)
    parser.add_argument("--text", default=DEFAULT_TEXT)
    parser.add_argument("--image", default="", help="真实图片路径；不传则自动生成等价测试图")
    parser.add_argument("--socket", default=DEFAULT_SOCKET_PATH)
    parser.add_argument("--rollout", default=DEFAULT_ROLLOUT_PATH)
    parser.add_argument("--log", default=DEFAULT_LOG_PATH)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--poll", type=float, default=DEFAULT_POLL_SECONDS)
    return parser.parse_args()


def ensure_file(path: str, label: str) -> None:
    if not os.path.exists(path):
        raise SystemExit(f"{label} 不存在：{path}")


def send_request(socket_path: str, payload: dict[str, Any]) -> dict[str, Any]:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(socket_path)
        raw = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        client.sendall(raw)
        client.shutdown(socket.SHUT_WR)
        response_chunks: list[bytes] = []
        while True:
            chunk = client.recv(65536)
            if not chunk:
                break
            response_chunks.append(chunk)
    response_raw = b"".join(response_chunks).decode("utf-8").strip()
    if not response_raw:
        raise SystemExit("owner bridge 未返回内容")
    return json.loads(response_raw)


def build_default_probe_image(project_root: Path) -> str:
    repo_png = project_root / "docs" / "screenshots" / "setup.png"
    if repo_png.exists():
        return str(repo_png)

    probe_dir = Path(tempfile.gettempdir()) / "codex-image-send-probe"
    probe_dir.mkdir(parents=True, exist_ok=True)
    ppm_path = probe_dir / "fallback-probe.ppm"
    ppm_path.write_text(
        "P3\n4 4\n255\n"
        "17 24 39 17 24 39 17 24 39 17 24 39\n"
        "17 24 39 59 130 246 59 130 246 17 24 39\n"
        "17 24 39 59 130 246 59 130 246 17 24 39\n"
        "17 24 39 17 24 39 17 24 39 17 24 39\n",
        encoding="ascii",
    )
    ensure_file(str(ppm_path), "生成的测试图")
    return str(ppm_path)


def locate_rollout(thread_id: str, fallback_path: str) -> str:
    matches = glob.glob(os.path.expanduser(f"~/.codex/sessions/**/rollout-*{thread_id}.jsonl"), recursive=True)
    if matches:
        matches.sort(key=lambda path: os.path.getmtime(path), reverse=True)
        return matches[0]
    return fallback_path


def read_events_since(rollout_path: str, offset: int) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with open(rollout_path, "rb") as handle:
        handle.seek(offset)
        for raw_line in handle:
            line = raw_line.decode("utf-8").strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def collect_log_lines(log_path: str, start_marker: str, thread_id: str) -> list[str]:
    if not os.path.exists(log_path):
        return []
    lines: list[str] = []
    with open(log_path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            if start_marker and raw_line < start_marker:
                continue
            if thread_id not in raw_line:
                continue
            if "resolve_topic" in raw_line or "topic_id 仍为 None" in raw_line or "item/completed" in raw_line:
                lines.append(raw_line.rstrip())
    return lines


def summarize_events(events: list[dict[str, Any]], text: str) -> tuple[bool, bool, list[str]]:
    user_turn_seen = False
    image_input_seen = False
    assistant_messages: list[str] = []

    for event in events:
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue

        if event.get("type") == "response_item":
            if payload.get("type") == "message" and payload.get("role") == "user":
                for item in payload.get("content", []):
                    if not isinstance(item, dict):
                        continue
                    if item.get("type") == "input_text" and item.get("text") == text:
                        user_turn_seen = True
                    item_type = str(item.get("type") or "")
                    if item_type in {"input_image", "localImage", "image"}:
                        image_input_seen = True

        if event.get("type") == "event_msg":
            if payload.get("type") == "user_message":
                if payload.get("message") == text:
                    user_turn_seen = True
                if payload.get("images") or payload.get("local_images"):
                    image_input_seen = True
            if payload.get("type") == "agent_message":
                message = str(payload.get("message") or "").strip()
                if message:
                    assistant_messages.append(message)

    return user_turn_seen, image_input_seen, assistant_messages


def run_probe(args: argparse.Namespace) -> ProbeSummary:
    ensure_file(args.socket, "codex owner bridge socket")
    ensure_file(args.rollout, "默认 rollout")
    ensure_file(args.log, "onlineworker 日志")

    project_root = Path(__file__).resolve().parents[1]
    image_path = args.image.strip() or build_default_probe_image(project_root)
    ensure_file(image_path, "测试图片")

    initial_rollout = locate_rollout(args.thread_id, args.rollout)
    ensure_file(initial_rollout, "目标 rollout")
    initial_offset = os.path.getsize(initial_rollout)

    send_started_at = time.time()
    send_started_marker = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(send_started_at))
    payload = {
        "type": "send_message",
        "thread_id": args.thread_id,
        "text": args.text,
        "cwd": args.cwd,
        "attachments": [
            {
                "kind": "image",
                "path": image_path,
                "name": os.path.basename(image_path),
            }
        ],
    }
    response = send_request(args.socket, payload)
    if response.get("ok") is not True:
        raise SystemExit(f"owner bridge 返回失败：{json.dumps(response, ensure_ascii=False)}")

    effective_thread_id = str(response.get("thread_id") or args.thread_id)
    effective_rollout = locate_rollout(effective_thread_id, initial_rollout)
    deadline = time.time() + float(args.timeout)
    user_turn_seen = False
    image_input_seen = False
    assistant_messages: list[str] = []

    offset = initial_offset if effective_rollout == initial_rollout else 0
    while time.time() < deadline:
        if os.path.exists(effective_rollout):
            events = read_events_since(effective_rollout, offset)
            current_user_seen, current_image_seen, current_assistant = summarize_events(events, args.text)
            user_turn_seen = user_turn_seen or current_user_seen
            image_input_seen = image_input_seen or current_image_seen
            if current_assistant:
                assistant_messages.extend(current_assistant)
            offset = os.path.getsize(effective_rollout)
            if user_turn_seen and image_input_seen and assistant_messages:
                break
        time.sleep(float(args.poll))

    topic_resolution_errors = collect_log_lines(args.log, send_started_marker, effective_thread_id)
    elapsed_seconds = round(time.time() - send_started_at, 2)
    return ProbeSummary(
        owner_bridge_response=response,
        effective_thread_id=effective_thread_id,
        rollout_path=effective_rollout,
        user_turn_seen=user_turn_seen,
        image_input_seen=image_input_seen,
        assistant_messages=assistant_messages,
        topic_resolution_errors=topic_resolution_errors,
        elapsed_seconds=elapsed_seconds,
    )


def main() -> int:
    args = parse_args()
    summary = run_probe(args)
    print(
        json.dumps(
            {
                "owner_bridge_response": summary.owner_bridge_response,
                "effective_thread_id": summary.effective_thread_id,
                "rollout_path": summary.rollout_path,
                "user_turn_seen": summary.user_turn_seen,
                "image_input_seen": summary.image_input_seen,
                "assistant_messages": summary.assistant_messages,
                "topic_resolution_errors": summary.topic_resolution_errors,
                "elapsed_seconds": summary.elapsed_seconds,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
