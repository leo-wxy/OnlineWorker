from __future__ import annotations

import asyncio
import copy
import json
import logging
import sys
from http import HTTPStatus
from typing import Any
from urllib.parse import urljoin

import httpx

from core.user_messages.contracts import UserMessageHookContext
from core.user_messages.hooks import run_before_user_message_send_hooks


logger = logging.getLogger(__name__)

DEFAULT_CLAUDE_UPSTREAM_BASE_URL = "https://api.anthropic.com"
REDACT_KEYS = {"authorization", "cookie", "token", "secret", "api_key", "api-key", "x-api-key"}
HOP_BY_HOP_HEADERS = {
    "connection",
    "content-length",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
MESSAGE_REWRITE_TEMPORARILY_DISABLED = True


def _truncate(value: str, limit: int = 240) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + f"...<truncated {len(value) - limit} chars>"


def redact_headers(headers: Any) -> dict[str, str]:
    redacted: dict[str, str] = {}
    items = getattr(headers, "items", None)
    iterable = items() if callable(items) else []
    for key, value in iterable:
        lowered = str(key).lower()
        if any(marker in lowered for marker in REDACT_KEYS):
            redacted[str(key)] = "[REDACTED]"
        else:
            redacted[str(key)] = str(value)
    return redacted


def _iter_user_text_slots(payload: dict[str, Any]):
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return

    for message_index, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        if str(message.get("role") or "").strip().lower() != "user":
            continue

        content = message.get("content")
        if isinstance(content, str):
            yield f"messages[{message_index}].content", message, "content", content
            continue

        if not isinstance(content, list):
            continue
        for content_index, item in enumerate(content):
            if not isinstance(item, dict):
                continue
            if str(item.get("type") or "").strip().lower() != "text":
                continue
            text = item.get("text")
            if isinstance(text, str):
                yield f"messages[{message_index}].content[{content_index}].text", item, "text", text


def _is_claude_injected_context_text(text: str) -> bool:
    return str(text or "").lstrip().startswith("<system-reminder>")


async def _rewrite_user_text(
    state,
    *,
    text: str,
    source: str,
    path: str,
) -> tuple[str, bool]:
    result = await run_before_user_message_send_hooks(
        state,
        text,
        UserMessageHookContext(
            source=source,
            provider_id="claude",
            workspace_id="",
            thread_id="",
            has_attachments=False,
            metadata={
                "claude_http_proxy": True,
                "json_path": path,
            },
        ),
    )
    return result.text, result.changed


async def rewrite_claude_json_payload(
    state,
    payload: dict[str, Any],
    *,
    source: str = "claude_http_proxy",
) -> tuple[dict[str, Any], bool, list[dict[str, str]]]:
    _ = state
    _ = source
    if MESSAGE_REWRITE_TEMPORARILY_DISABLED:
        return payload, False, []

    if not isinstance(payload, dict):
        return payload, False, []

    rewritten = copy.deepcopy(payload)
    changed = False
    changes: list[dict[str, str]] = []

    for path, holder, key, original in list(_iter_user_text_slots(rewritten) or []):
        if _is_claude_injected_context_text(original):
            continue
        next_text, text_changed = await _rewrite_user_text(
            state,
            text=original,
            source=source,
            path=path,
        )
        if not text_changed:
            continue
        holder[key] = next_text
        changed = True
        changes.append(
            {
                "path": path,
                "before": original,
                "after": next_text,
            }
        )

    return rewritten, changed, changes


def summarize_claude_payload(raw: str | bytes, *, preview_limit: int = 500) -> str:
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return f"bytes={len(raw)}"

    try:
        payload = json.loads(raw)
    except Exception:
        return _truncate(str(raw).replace("\n", "\\n"), preview_limit)

    if not isinstance(payload, dict):
        return _truncate(json.dumps(payload, ensure_ascii=False), preview_limit)

    parts: list[str] = []
    model = payload.get("model")
    if model:
        parts.append(f"model={model}")

    messages = payload.get("messages")
    if isinstance(messages, list):
        parts.append(f"messages={len(messages)}")
        texts: list[str] = []
        for _path, _holder, _key, text in list(_iter_user_text_slots(payload) or []):
            texts.append(text)
        if texts:
            parts.append(f"text={_truncate(' | '.join(texts), 220)}")

    if not parts:
        return _truncate(json.dumps(payload, ensure_ascii=False), preview_limit)
    return " ".join(parts)


def _write_probe_event(event: dict[str, Any]) -> None:
    sys.stderr.write(
        "[claude-http-proxy] "
        + json.dumps(event, ensure_ascii=False, sort_keys=True)
        + "\n"
    )
    sys.stderr.flush()


def _target_url(upstream_base_url: str | None, raw_path: str) -> str:
    base = str(upstream_base_url or "").strip() or DEFAULT_CLAUDE_UPSTREAM_BASE_URL
    base = base.rstrip("/") + "/"
    path = str(raw_path or "/").lstrip("/")
    return urljoin(base, path)


def _filtered_request_headers(headers: dict[str, str]) -> dict[str, str]:
    filtered: dict[str, str] = {}
    for key, value in headers.items():
        lowered = key.lower()
        if lowered in HOP_BY_HOP_HEADERS or lowered == "host":
            continue
        filtered[key] = value
    return filtered


def _filtered_response_headers(headers: httpx.Headers) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for key, value in headers.multi_items():
        if key.lower() in HOP_BY_HOP_HEADERS:
            continue
        result.append((key, value))
    return result


async def _read_http_request(reader: asyncio.StreamReader) -> tuple[str, str, dict[str, str], bytes] | None:
    header_bytes = await reader.readuntil(b"\r\n\r\n")
    header_text = header_bytes.decode("iso-8859-1")
    lines = header_text.split("\r\n")
    request_line = lines[0]
    parts = request_line.split(" ", 2)
    if len(parts) < 2:
        return None
    method, path = parts[0].upper(), parts[1]
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        headers[key.strip()] = value.strip()
    content_length = int(headers.get("Content-Length") or headers.get("content-length") or 0)
    body = await reader.readexactly(content_length) if content_length > 0 else b""
    return method, path, headers, body


class ClaudeHttpProxy:
    """Local HTTP proxy for Claude CLI API traffic.

    The wrapper points Claude Code at this proxy through ANTHROPIC_BASE_URL. The
    proxy rewrites user message text in Anthropic-compatible JSON payloads, then
    forwards the request to the real upstream base URL.
    """

    def __init__(
        self,
        *,
        state,
        upstream_base_url: str | None = None,
        listen_host: str = "127.0.0.1",
        listen_port: int = 0,
        rewrite: bool = False,
        probe: bool = False,
    ) -> None:
        self.state = state
        self.upstream_base_url = upstream_base_url or DEFAULT_CLAUDE_UPSTREAM_BASE_URL
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.rewrite = rewrite
        self.probe = probe
        self.listen_url = ""
        self._server: asyncio.base_events.Server | None = None

    async def start(self) -> str:
        if self._server is not None:
            return self.listen_url

        self._server = await asyncio.start_server(
            self._handle_client,
            self.listen_host,
            self.listen_port,
        )
        socket = next(iter(self._server.sockets or []), None)
        if socket is None:
            raise RuntimeError("claude http proxy 未能获取监听 socket")
        host, port = socket.getsockname()[:2]
        host_value = "127.0.0.1" if host in {"0.0.0.0", "::"} else str(host)
        self.listen_url = f"http://{host_value}:{port}"
        logger.info(
            "[claude-http-proxy] listening=%s upstream=%s rewrite=%s probe=%s",
            self.listen_url,
            self.upstream_base_url,
            self.rewrite,
            self.probe,
        )
        return self.listen_url

    async def stop(self) -> None:
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None
        self.listen_url = ""

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            request = await _read_http_request(reader)
            if request is None:
                await self._write_error(writer, 400, "bad request")
                return
            method, path, headers, body = request
            await self._proxy_request(writer, method, path, headers, body)
        except asyncio.IncompleteReadError:
            await self._write_error(writer, 400, "incomplete request")
        except Exception as exc:
            logger.warning("[claude-http-proxy] request failed", exc_info=True)
            await self._write_error(writer, 502, str(exc))
        finally:
            writer.close()
            await writer.wait_closed()

    async def _proxy_request(
        self,
        writer: asyncio.StreamWriter,
        method: str,
        path: str,
        headers: dict[str, str],
        body: bytes,
    ) -> None:
        outbound_body = body
        content_type = next(
            (value for key, value in headers.items() if key.lower() == "content-type"),
            "",
        )

        if self.probe:
            _write_probe_event(
                {
                    "event": "request",
                    "method": method,
                    "path": path,
                    "headers": redact_headers(headers),
                    "summary": summarize_claude_payload(body),
                }
            )
            logger.info(
                "[claude-http-proxy] request method=%s path=%s headers=%s summary=%s",
                method,
                path,
                redact_headers(headers),
                summarize_claude_payload(body),
            )

        if self.rewrite and "json" in content_type.lower() and body:
            try:
                payload = json.loads(body.decode("utf-8"))
            except Exception:
                payload = None
            if isinstance(payload, dict):
                rewritten, changed, changes = await rewrite_claude_json_payload(
                    self.state,
                    payload,
                    source="claude_http_proxy",
                )
                if changed:
                    outbound_body = json.dumps(
                        rewritten,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
                    for change in changes:
                        if self.probe:
                            _write_probe_event(
                                {
                                    "event": "rewrite",
                                    "path": change["path"],
                                    "before": change["before"],
                                    "after": change["after"],
                                }
                            )
                        logger.info(
                            "[claude-http-proxy] 已改写 Claude CLI 用户输入 path=%s before_len=%s after_len=%s",
                            change["path"],
                            len(change["before"]),
                            len(change["after"]),
                        )

        target = _target_url(self.upstream_base_url, path)
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                method,
                target,
                headers=_filtered_request_headers(headers),
                content=outbound_body,
            ) as response:
                await self._write_response_headers(writer, response)
                async for chunk in response.aiter_raw():
                    if not chunk:
                        continue
                    writer.write(f"{len(chunk):x}\r\n".encode("ascii"))
                    writer.write(chunk)
                    writer.write(b"\r\n")
                    await writer.drain()
                writer.write(b"0\r\n\r\n")
                await writer.drain()

    async def _write_response_headers(
        self,
        writer: asyncio.StreamWriter,
        response: httpx.Response,
    ) -> None:
        reason = HTTPStatus(response.status_code).phrase if response.status_code in HTTPStatus._value2member_map_ else ""
        writer.write(f"HTTP/1.1 {response.status_code} {reason}\r\n".encode("ascii"))
        for key, value in _filtered_response_headers(response.headers):
            writer.write(f"{key}: {value}\r\n".encode("iso-8859-1"))
        writer.write(b"Transfer-Encoding: chunked\r\n")
        writer.write(b"Connection: close\r\n")
        writer.write(b"\r\n")
        await writer.drain()

    async def _write_error(
        self,
        writer: asyncio.StreamWriter,
        status_code: int,
        message: str,
    ) -> None:
        payload = json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")
        reason = HTTPStatus(status_code).phrase
        writer.write(
            (
                f"HTTP/1.1 {status_code} {reason}\r\n"
                "Content-Type: application/json; charset=utf-8\r\n"
                f"Content-Length: {len(payload)}\r\n"
                "Connection: close\r\n"
                "\r\n"
            ).encode("ascii")
        )
        writer.write(payload)
        await writer.drain()
