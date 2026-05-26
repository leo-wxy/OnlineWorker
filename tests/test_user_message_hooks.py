import pytest


def test_sensitive_term_neutralizer_drops_abuse_prefix_and_keeps_intent():
    from core.user_messages.neutralizer import neutralize_abusive_language

    result = neutralize_abusive_language("你妈的，这什么傻逼问题")

    assert result.text == "这是什么问题"
    assert result.changed is True
    assert [match.value for match in result.matches] == ["你妈的", "傻逼"]


def test_sensitive_term_neutralizer_drops_venting_prefix_without_dropping_question():
    from core.user_messages.neutralizer import neutralize_abusive_language

    result = neutralize_abusive_language("妈的，怎么又连不上了")

    assert result.text == "怎么又连不上了"
    assert result.changed is True
    assert [match.value for match in result.matches] == ["妈的"]


def test_sensitive_term_neutralizer_can_clear_pure_abuse():
    from core.user_messages.neutralizer import neutralize_abusive_language

    result = neutralize_abusive_language("你妈的")

    assert result.text == ""
    assert result.changed is True
    assert [match.value for match in result.matches] == ["你妈的"]


def test_sensitive_term_neutralizer_replaces_derogatory_object_phrase():
    from core.user_messages.neutralizer import neutralize_abusive_language

    result = neutralize_abusive_language("这破玩意怎么一直报错")

    assert result.text == "这个怎么一直报错"
    assert result.changed is True


def test_abusive_language_normalization_removes_abusive_modifier():
    from core.user_messages.builtin_hooks import normalize_abusive_language

    result = normalize_abusive_language("这什么傻逼问题")

    assert result.text == "这是什么问题"
    assert result.changed is True
    assert result.hook_id == "abusive_language_normalization"


def test_abusive_language_normalization_preserves_fenced_code_blocks():
    from core.user_messages.builtin_hooks import normalize_abusive_language

    source = "帮我看下这个问题\n```text\n这什么傻逼问题\n```\n这什么傻逼逻辑"

    result = normalize_abusive_language(source)

    assert "```text\n这什么傻逼问题\n```" in result.text
    assert result.text.endswith("这什么逻辑")
    assert result.changed is True


@pytest.mark.asyncio
async def test_before_send_hooks_skip_slash_commands():
    from core.user_messages.contracts import UserMessageHookContext
    from core.user_messages.hooks import run_before_user_message_send_hooks

    context = UserMessageHookContext(
        source="telegram",
        provider_id="codex",
        workspace_id="codex:/tmp/project",
        thread_id="tid-1",
        has_attachments=False,
    )

    result = await run_before_user_message_send_hooks(
        None,
        "/review 这什么傻逼问题",
        context,
    )

    assert result.text == "/review 这什么傻逼问题"
    assert result.changed is False


@pytest.mark.asyncio
async def test_before_send_hooks_can_be_disabled_from_config():
    from types import SimpleNamespace

    from core.user_messages.contracts import UserMessageHookContext
    from core.user_messages.hooks import run_before_user_message_send_hooks

    context = UserMessageHookContext(
        source="telegram",
        provider_id="codex",
        workspace_id="codex:/tmp/project",
        thread_id="tid-1",
        has_attachments=False,
    )
    state = SimpleNamespace(config=SimpleNamespace(message_hooks=SimpleNamespace(enabled=False)))

    result = await run_before_user_message_send_hooks(
        state,
        "这什么傻逼问题",
        context,
    )

    assert result.text == "这什么傻逼问题"
    assert result.changed is False


@pytest.mark.asyncio
async def test_before_send_hooks_treat_builtin_mode_off_as_disabled():
    from types import SimpleNamespace

    from core.user_messages.contracts import UserMessageHookContext
    from core.user_messages.hooks import run_before_user_message_send_hooks

    context = UserMessageHookContext(
        source="telegram",
        provider_id="codex",
        workspace_id="codex:/tmp/project",
        thread_id="tid-1",
        has_attachments=False,
    )
    state = SimpleNamespace(
        config=SimpleNamespace(
            message_hooks=SimpleNamespace(
                enabled=True,
                builtin={
                    "abusive_language_normalization": SimpleNamespace(
                        enabled=True,
                        mode="off",
                    )
                },
            )
        )
    )

    result = await run_before_user_message_send_hooks(
        state,
        "这什么傻逼问题",
        context,
    )

    assert result.text == "这什么傻逼问题"
    assert result.changed is False


@pytest.mark.asyncio
async def test_gateway_prepares_user_message_text_from_request():
    from core.user_messages.contracts import UserMessageSendRequest
    from core.user_messages.gateway import prepare_user_message_text

    result = await prepare_user_message_text(
        None,
        UserMessageSendRequest(
            source="owner_bridge",
            provider_id="codex",
            workspace_id="codex:/tmp/project",
            thread_id="tid-1",
            text="这什么傻逼问题",
            attachments=[],
        ),
    )

    assert result.text == "这是什么问题"
    assert result.changed is True


@pytest.mark.asyncio
async def test_gateway_uses_provider_message_hook_enablement():
    from types import SimpleNamespace

    from core.user_messages.contracts import UserMessageSendRequest
    from core.user_messages.gateway import prepare_user_message_text

    class _Config:
        message_hooks = SimpleNamespace(enabled=True)
        providers = {
            "codex": SimpleNamespace(
                message_hooks=SimpleNamespace(
                    enabled=True,
                    builtin={
                        "abusive_language_normalization": SimpleNamespace(
                            enabled=True,
                            mode="conservative",
                        )
                    },
                )
            ),
            "claude": SimpleNamespace(
                message_hooks=SimpleNamespace(
                    enabled=True,
                    builtin={
                        "abusive_language_normalization": SimpleNamespace(
                            enabled=False,
                            mode="conservative",
                        )
                    },
                )
            ),
        }

        def get_provider(self, name):
            return self.providers.get(name)

    state = SimpleNamespace(config=_Config())

    codex_result = await prepare_user_message_text(
        state,
        UserMessageSendRequest(
            source="owner_bridge",
            provider_id="codex",
            workspace_id="codex:/tmp/project",
            thread_id="tid-codex",
            text="这什么傻逼问题",
            attachments=[],
        ),
    )
    claude_result = await prepare_user_message_text(
        state,
        UserMessageSendRequest(
            source="owner_bridge",
            provider_id="claude",
            workspace_id="claude:/tmp/project",
            thread_id="tid-claude",
            text="这什么傻逼问题",
            attachments=[],
        ),
    )

    assert codex_result.text == "这是什么问题"
    assert codex_result.changed is True
    assert claude_result.text == "这什么傻逼问题"
    assert claude_result.changed is False
