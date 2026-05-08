from bot.command_rules import get_command_rule


def test_workspace_command_is_global_strict():
    rule = get_command_rule("workspace")

    assert rule is not None
    assert rule.scope == "global"
    assert rule.scope_policy == "strict"
    assert rule.executor == "bot"


def test_list_command_is_workspace_fallback():
    rule = get_command_rule("list")

    assert rule is not None
    assert rule.scope == "workspace"
    assert rule.scope_policy == "fallback"
    assert rule.executor == "bot"


def test_model_command_is_thread_strict_wrapper():
    rule = get_command_rule("model")

    assert rule is not None
    assert rule.scope == "thread"
    assert rule.scope_policy == "strict"
    assert rule.executor == "downstream"
    assert rule.telegram_behavior == "wrapper"
    assert rule.tool_name is None


def test_help_command_is_contextual_hybrid():
    rule = get_command_rule("help")

    assert rule is not None
    assert rule.scope == "contextual"
    assert rule.scope_policy == "contextual"
    assert rule.executor == "hybrid"
    assert rule.thread_downstream_priority is False


def test_permissions_command_is_thread_passthrough_not_wrapper():
    rule = get_command_rule("permissions")

    assert rule is not None
    assert rule.scope == "thread"
    assert rule.scope_policy == "strict"
    assert rule.executor == "downstream"
    assert rule.telegram_behavior == "passthrough"
