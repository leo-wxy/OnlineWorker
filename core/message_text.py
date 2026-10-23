import re


_APPSHOT_CONTEXT_RE = re.compile(
    r"^[ \t]*(?:# Applications mentioned by the user:[ \t]*\r?\n\s*)?"
    r"(?:<appshot\b[^>]*>[\s\S]*?</appshot>"
    r"|&lt;appshot\b[\s\S]*?&gt;[\s\S]*?&lt;/appshot&gt;)"
    r"[ \t]*(?:\r?\n)?",
    re.MULTILINE,
)
_APP_REQUEST_HEADER_RE = re.compile(r"\A\s*## My request:[ \t]*(?:\r?\n|$)")
_INTERNAL_CITATION_SUFFIXES = (
    ("<oai-mem-citation>", "</oai-mem-citation>"),
    ("<citation_entries>", "</rollout_ids>"),
    ("&lt;oai-mem-citation&gt;", "&lt;/oai-mem-citation&gt;"),
    ("&lt;citation_entries&gt;", "&lt;/rollout_ids&gt;"),
)


def strip_appshot_context(text: str) -> str:
    if "appshot" not in text:
        return text
    cleaned, count = _APPSHOT_CONTEXT_RE.subn("", text)
    if not count:
        return text
    return _APP_REQUEST_HEADER_RE.sub("", cleaned).strip()


def strip_internal_citation_suffix(text: str) -> str:
    stripped = text.rstrip()
    for opening, closing in _INTERNAL_CITATION_SUFFIXES:
        start = stripped.rfind(opening)
        if (
            start >= 0
            and stripped.endswith(closing)
            and (start == 0 or stripped[start - 1] == "\n")
        ):
            return stripped[:start].rstrip()
    return text
