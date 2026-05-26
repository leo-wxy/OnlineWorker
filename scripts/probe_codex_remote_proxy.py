#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
from typing import Any

import websockets


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.user_messages.neutralizer import neutralize_abusive_language  # noqa: E402


TEXT_INPUT_TYPES = {"text"}
REWRITE_METHODS = {"turn/start", "turn/steer"}
REDACT_KEYS = {"authorization", "cookie", "token", "secret", "api_key", "api-key", "x-api-key"}


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + f"...<truncated {len(value) - limit} chars>"


def _redact_headers(headers: Any) -> dict[str, str]:
    redacted: dict[str, str] = {}
    for key, value in getattr(headers, "items", lambda: [])():
        lowered = str(key).lower()
        if any(marker in lowered for marker in REDACT_KEYS):
            redacted[str(key)] = "[REDACTED]"
        else:
            redacted[str(key)] = str(value)
    return redacted


def summarize_json_message(raw: str, *, preview_limit: int = 500) -> str:
    try:
        payload = json.loads(raw)
    except Exception:
        return _truncate(raw.replace("\n", "\\n"), preview_limit)

    if not isinstance(payload, dict):
        return _truncate(json.dumps(payload, ensure_ascii=False), preview_limit)

    parts: list[str] = []
    if "id" in payload:
        parts.append(f"id={payload.get('id')}")
    if "method" in payload:
        parts.append(f"method={payload.get('method')}")

    params = payload.get("params")
    if isinstance(params, dict):
        thread_id = params.get("threadId") or params.get("thread_id")
        if thread_id:
            parts.append(f"thread={str(thread_id)[:18]}")
        input_items = params.get("input")
        if isinstance(input_items, list):
            texts = [
                str(item.get("text"))
                for item in input_items
                if isinstance(item, dict) and isinstance(item.get("text"), str)
            ]
            if texts:
                parts.append(f"text={_truncate(' | '.join(texts), 180)}")

    if "result" in payload:
        parts.append("result")
    if "error" in payload:
        parts.append(f"error={_truncate(str(payload.get('error')), 180)}")

    if not parts:
        return _truncate(json.dumps(payload, ensure_ascii=False), preview_limit)
    return " ".join(parts)


def rewrite_codex_client_message(raw: str) -> tuple[str, bool, list[dict[str, str]]]:
    try:
        payload = json.loads(raw)
    except Exception:
        return raw, False, []

    if not isinstance(payload, dict):
        return raw, False, []

    method = payload.get("method")
    if method not in REWRITE_METHODS:
        return raw, False, []

    params = payload.get("params")
    if not isinstance(params, dict):
        return raw, False, []

    input_items = params.get("input")
    if not isinstance(input_items, list):
        return raw, False, []

    changed = False
    changes: list[dict[str, str]] = []
    for item in input_items:
        if not isinstance(item, dict):
            continue
        if item.get("type") not in TEXT_INPUT_TYPES:
            continue
        text = item.get("text")
        if not isinstance(text, str):
            continue

        result = neutralize_abusive_language(text)
        if not result.changed:
            continue

        item["text"] = result.text
        changed = True
        changes.append(
            {
                "method": str(method),
                "before": text,
                "after": result.text,
            }
        )

    if not changed:
        return raw, False, []
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")), True, changes


class CodexRemoteProxyProbe:
    def __init__(
        self,
        *,
        listen_host: str,
        listen_port: int,
        upstream: str | None = None,
        rewrite: bool = False,
        max_messages: int = 0,
        preview_limit: int = 1000,
    ) -> None:
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.upstream = upstream
        self.rewrite = rewrite
        self.max_messages = max_messages
        self.preview_limit = preview_limit
        self._message_count = 0
        self._stop = asyncio.Event()

    async def run(self) -> None:
        async with websockets.serve(
            self._handle_client,
            self.listen_host,
            self.listen_port,
            max_size=None,
            ping_interval=None,
            ping_timeout=None,
        ):
            print(
                json.dumps(
                    {
                        "event": "listening",
                        "url": f"ws://{self.listen_host}:{self.listen_port}",
                        "upstream": self.upstream,
                        "rewrite": self.rewrite,
                        "max_messages": self.max_messages,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            await self._stop.wait()

    async def _handle_client(self, client: websockets.ServerConnection) -> None:
        request = getattr(client, "request", None)
        path = getattr(request, "path", "") if request is not None else ""
        headers = _redact_headers(getattr(request, "headers", None)) if request is not None else {}
        print(
            json.dumps(
                {
                    "event": "client_connected",
                    "path": path,
                    "headers": headers,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

        if self.upstream:
            async with websockets.connect(
                self.upstream,
                max_size=None,
                ping_interval=None,
                ping_timeout=None,
                proxy=None,
            ) as upstream:
                await asyncio.gather(
                    self._relay_client_to_upstream(client, upstream),
                    self._relay_upstream_to_client(upstream, client),
                )
            return

        async for message in client:
            await self._log_message("client->probe", message)
            if self._should_stop():
                break

    async def _relay_client_to_upstream(
        self,
        client: websockets.ServerConnection,
        upstream: websockets.ClientConnection,
    ) -> None:
        async for message in client:
            await self._log_message("client->upstream", message)
            outbound = message
            if self.rewrite and isinstance(message, str):
                outbound, changed, changes = rewrite_codex_client_message(message)
                for change in changes:
                    print(
                        json.dumps(
                            {
                                "event": "rewritten",
                                "method": change["method"],
                                "before": change["before"],
                                "after": change["after"],
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
                if changed:
                    await self._log_message("client->upstream_rewritten", outbound)
            await upstream.send(outbound)
            if self._should_stop():
                break

    async def _relay_upstream_to_client(
        self,
        upstream: websockets.ClientConnection,
        client: websockets.ServerConnection,
    ) -> None:
        async for message in upstream:
            await self._log_message("upstream->client", message)
            await client.send(message)
            if self._should_stop():
                break

    async def _log_message(self, direction: str, message: str | bytes) -> None:
        self._message_count += 1
        if isinstance(message, bytes):
            payload = {
                "event": "message",
                "direction": direction,
                "number": self._message_count,
                "bytes": len(message),
                "binary_preview_hex": message[:80].hex(),
            }
        else:
            payload = {
                "event": "message",
                "direction": direction,
                "number": self._message_count,
                "summary": summarize_json_message(message, preview_limit=self.preview_limit),
                "raw": _truncate(message, self.preview_limit),
            }
        print(json.dumps(payload, ensure_ascii=False), flush=True)

    def _should_stop(self) -> bool:
        if self.max_messages <= 0:
            return False
        if self._message_count < self.max_messages:
            return False
        self._stop.set()
        return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Probe or proxy Codex CLI --remote app-server websocket messages."
    )
    parser.add_argument("--listen-host", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, default=18789)
    parser.add_argument("--upstream", help="Real app-server websocket URL to proxy to")
    parser.add_argument("--rewrite", action="store_true", help="Rewrite turn/start and turn/steer text input")
    parser.add_argument("--max-messages", type=int, default=0, help="Stop after this many websocket messages")
    parser.add_argument("--preview-limit", type=int, default=1000)
    args = parser.parse_args(argv)

    probe = CodexRemoteProxyProbe(
        listen_host=args.listen_host,
        listen_port=args.listen_port,
        upstream=args.upstream,
        rewrite=args.rewrite,
        max_messages=args.max_messages,
        preview_limit=args.preview_limit,
    )
    try:
        asyncio.run(probe.run())
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
