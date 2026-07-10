from __future__ import annotations

from typing import Any

from core.user_messages.builtin_hooks import normalize_abusive_language
from core.user_messages.contracts import UserMessageHookContext, UserMessageHookResult


def _message_hooks_config(state: Any):
    config = getattr(state, "config", None) if state is not None else None
    return getattr(config, "message_hooks", None) if config is not None else None


def _provider_message_hooks_config(state: Any, provider_id: str):
    config = getattr(state, "config", None) if state is not None else None
    if config is None:
        return None

    provider = None
    get_provider = getattr(config, "get_provider", None)
    if callable(get_provider):
        provider = get_provider(provider_id)
    if provider is None:
        providers = getattr(config, "providers", None)
        if isinstance(providers, dict):
            provider = providers.get(provider_id)
    return getattr(provider, "message_hooks", None) if provider is not None else None


def _effective_message_hooks_config(state: Any, provider_id: str):
    return _provider_message_hooks_config(state, provider_id) or _message_hooks_config(state)

def _hook_enabled_for_context(state: Any, hook_name: str, context: UserMessageHookContext) -> bool:
    message_hooks = _effective_message_hooks_config(state, context.provider_id)
    return _hook_enabled_from_config(message_hooks, hook_name)


def _hook_enabled_from_config(message_hooks: Any, hook_name: str) -> bool:
    if message_hooks is None:
        return True
    if getattr(message_hooks, "enabled", True) is False:
        return False
    builtin = getattr(message_hooks, "builtin", {}) or {}
    hook_config = builtin.get(hook_name) if isinstance(builtin, dict) else None
    if hook_config is None:
        return True
    if str(getattr(hook_config, "mode", "") or "").strip().lower() == "off":
        return False
    return bool(getattr(hook_config, "enabled", True))


def should_skip_before_send_hooks(text: str | None, context: UserMessageHookContext) -> bool:
    if not str(text or "").strip():
        return True
    if context.is_command_dispatch:
        return True
    if str(text or "").lstrip().startswith("/"):
        return True
    return False


async def run_before_user_message_send_hooks(
    state,
    text: str | None,
    context: UserMessageHookContext,
) -> UserMessageHookResult:
    original = str(text or "")
    if should_skip_before_send_hooks(original, context):
        return UserMessageHookResult(text=original)
    if not _hook_enabled_for_context(state, "abusive_language_normalization", context):
        return UserMessageHookResult(text=original)
    return normalize_abusive_language(original)
