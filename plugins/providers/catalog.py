from __future__ import annotations

from collections.abc import Callable, Iterable

from core.providers.contracts import ProviderDescriptor
from plugins.providers.builtin.claude.python.provider import create_provider_descriptor as create_claude_descriptor
from plugins.providers.builtin.codex.python.provider import create_provider_descriptor as create_codex_descriptor


def iter_bundled_provider_factories() -> Iterable[Callable[[], ProviderDescriptor]]:
    return (
        create_claude_descriptor,
        create_codex_descriptor,
    )
