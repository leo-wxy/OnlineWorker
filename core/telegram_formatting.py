from __future__ import annotations

from dataclasses import dataclass
import html
import re


_CODE_FENCE_RE = re.compile(r"^```(?P<lang>[A-Za-z0-9_+-]+)?\s*$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(?P<text>.+?)\s*$")
_BULLET_RE = re.compile(r"^[-*+]\s+(?P<text>.+?)\s*$")
_ORDERED_RE = re.compile(r"^(?P<index>\d+)\.\s+(?P<text>.+?)\s*$")
_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_BOLD_RE = re.compile(r"\*\*([^*\n]+)\*\*|__([^_\n]+)__")
_ITALIC_RE = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)|(?<!_)_([^_\n]+)_(?!_)")
_STRIKE_RE = re.compile(r"~~([^~\n]+)~~")


@dataclass(frozen=True)
class TelegramRenderedText:
    text: str
    parse_mode: str | None
    fallback_text: str


def _utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _placeholder_substitute(
    text: str,
    pattern: re.Pattern[str],
    placeholders: dict[str, str],
    renderer,
) -> str:
    def _repl(match: re.Match[str]) -> str:
        key = f"@@TGHTML{len(placeholders)}@@"
        placeholders[key] = renderer(match)
        return key

    return pattern.sub(_repl, text)


def _restore_placeholders(text: str, placeholders: dict[str, str]) -> str:
    restored = html.escape(text, quote=False)
    for key, value in placeholders.items():
        restored = restored.replace(key, value)
    return restored


def _render_inline_markdown(text: str) -> str:
    placeholders: dict[str, str] = {}
    working = text
    working = _placeholder_substitute(
        working,
        _INLINE_CODE_RE,
        placeholders,
        lambda match: f"<code>{html.escape(match.group(1), quote=False)}</code>",
    )
    working = _placeholder_substitute(
        working,
        _LINK_RE,
        placeholders,
        lambda match: (
            f'<a href="{html.escape(match.group(2), quote=True)}">'
            f"{html.escape(match.group(1), quote=False)}</a>"
        ),
    )
    working = _placeholder_substitute(
        working,
        _BOLD_RE,
        placeholders,
        lambda match: (
            f"<b>{html.escape(next(group for group in match.groups() if group), quote=False)}</b>"
        ),
    )
    working = _placeholder_substitute(
        working,
        _ITALIC_RE,
        placeholders,
        lambda match: (
            f"<i>{html.escape(next(group for group in match.groups() if group), quote=False)}</i>"
        ),
    )
    working = _placeholder_substitute(
        working,
        _STRIKE_RE,
        placeholders,
        lambda match: f"<s>{html.escape(match.group(1), quote=False)}</s>",
    )
    return _restore_placeholders(working, placeholders)


def _render_list_block(lines: list[str], ordered: bool) -> str:
    rendered_items: list[str] = []
    for index, line in enumerate(lines, start=1):
        match = _ORDERED_RE.match(line.strip()) if ordered else _BULLET_RE.match(line.strip())
        if not match:
            continue
        prefix = f"{index}. " if ordered else "• "
        rendered_items.append(f"{prefix}{_render_inline_markdown(match.group('text'))}")
    return "\n".join(rendered_items)


def _render_blockquote_block(lines: list[str]) -> str:
    body = "\n".join(
        _render_inline_markdown(line.lstrip()[1:].lstrip())
        for line in lines
    )
    return f"<blockquote>{body}</blockquote>"


def _render_code_block(lines: list[str], lang: str) -> str:
    escaped_code = html.escape("\n".join(lines).rstrip("\n"), quote=False)
    class_attr = (
        f' class="language-{html.escape(lang, quote=True)}"'
        if lang
        else ""
    )
    return f"<pre><code{class_attr}>{escaped_code}</code></pre>"


def _is_block_start(line: str) -> bool:
    stripped = line.strip()
    return (
        not stripped
        or bool(_CODE_FENCE_RE.match(stripped))
        or bool(_HEADING_RE.match(stripped))
        or stripped.startswith(">")
        or bool(_BULLET_RE.match(stripped))
        or bool(_ORDERED_RE.match(stripped))
    )


def _render_markdown_to_telegram_html(text: str) -> str:
    lines = text.splitlines()
    blocks: list[str] = []
    index = 0

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            index += 1
            continue

        code_match = _CODE_FENCE_RE.match(stripped)
        if code_match:
            language = (code_match.group("lang") or "").strip()
            index += 1
            code_lines: list[str] = []
            while index < len(lines):
                closing = lines[index].strip()
                if _CODE_FENCE_RE.match(closing):
                    index += 1
                    break
                code_lines.append(lines[index])
                index += 1
            blocks.append(_render_code_block(code_lines, language))
            continue

        heading_match = _HEADING_RE.match(stripped)
        if heading_match:
            blocks.append(f"<b>{_render_inline_markdown(heading_match.group('text'))}</b>")
            index += 1
            continue

        if stripped.startswith(">"):
            quote_lines: list[str] = []
            while index < len(lines) and lines[index].strip().startswith(">"):
                quote_lines.append(lines[index])
                index += 1
            blocks.append(_render_blockquote_block(quote_lines))
            continue

        if _BULLET_RE.match(stripped):
            list_lines: list[str] = []
            while index < len(lines) and _BULLET_RE.match(lines[index].strip()):
                list_lines.append(lines[index])
                index += 1
            blocks.append(_render_list_block(list_lines, ordered=False))
            continue

        if _ORDERED_RE.match(stripped):
            list_lines = []
            while index < len(lines) and _ORDERED_RE.match(lines[index].strip()):
                list_lines.append(lines[index])
                index += 1
            blocks.append(_render_list_block(list_lines, ordered=True))
            continue

        paragraph_lines: list[str] = []
        while index < len(lines) and not _is_block_start(lines[index]):
            paragraph_lines.append(lines[index])
            index += 1
        if not paragraph_lines:
            paragraph_lines.append(line)
            index += 1
        blocks.append("\n".join(_render_inline_markdown(item) for item in paragraph_lines))

    return "\n".join(blocks) if blocks else html.escape(text, quote=False)


def format_telegram_assistant_final_text(
    text: str,
    *,
    max_length: int = 4096,
) -> TelegramRenderedText:
    normalized = (text or "").strip()
    if not normalized:
        return TelegramRenderedText(text="", parse_mode=None, fallback_text="")

    try:
        formatted = _render_markdown_to_telegram_html(normalized)
    except Exception:
        return TelegramRenderedText(
            text=normalized,
            parse_mode=None,
            fallback_text=normalized,
        )

    if not formatted or _utf16_len(formatted) > max_length:
        return TelegramRenderedText(
            text=normalized,
            parse_mode=None,
            fallback_text=normalized,
        )

    return TelegramRenderedText(
        text=formatted,
        parse_mode="HTML",
        fallback_text=normalized,
    )
