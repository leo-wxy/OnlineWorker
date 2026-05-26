from __future__ import annotations

from core.user_messages.contracts import UserMessageHookResult
from core.user_messages.neutralizer import neutralize_abusive_language


ABUSIVE_LANGUAGE_HOOK_ID = "abusive_language_normalization"


def normalize_abusive_language(text: str) -> UserMessageHookResult:
    original = str(text or "")
    if not original:
        return UserMessageHookResult(text=original)

    neutralized = neutralize_abusive_language(original)
    return UserMessageHookResult(
        text=neutralized.text,
        changed=neutralized.changed,
        hook_id=ABUSIVE_LANGUAGE_HOOK_ID if neutralized.changed else "",
        reason="removed_abusive_modifier" if neutralized.changed else "",
    )
