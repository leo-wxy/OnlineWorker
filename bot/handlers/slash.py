import logging
import time
from dataclasses import dataclass
from typing import Callable, Literal, Optional

from telegram import Update
from telegram.ext import ContextTypes

from bot.command_rules import get_command_rule
from bot.interaction_specs import (
    get_interaction_spec,
    get_wrapper_supported_providers,
    resolve_thread_command_wrapper,
    supports_thread_command_wrapper,
)
from bot.keyboards import build_command_wrapper_keyboard
from bot.telegram_command_aliases import resolve_registered_command_alias
from config import Config
from core.providers.registry import classify_provider, provider_not_enabled_message
from core.state import AppState
from bot.handlers.common import (
    _send_to_group,
    make_active_handler,
    make_echo_handler,
    make_help_handler,
    make_ping_handler,
    make_restart_handler,
    make_start_handler,
    make_status_handler,
    make_stop_handler,
)
from bot.handlers.message import make_message_handler
from bot.handlers.thread import (
    make_archive_thread_handler,
    make_history_handler,
    make_list_thread_handler,
    make_new_thread_handler,
    make_skills_handler,
)
from bot.handlers.workspace import make_cli_handler, make_workspace_handler

logger = logging.getLogger(__name__)

CommandContext = Literal["global", "workspace", "thread", "unknown"]


@dataclass(frozen=True)
class ParsedSlashCommand:
    name: str
    args: list[str]
    normalized_text: str


def parse_slash_command(text: str | None) -> Optional[ParsedSlashCommand]:
    if not text:
        return None

    stripped = text.strip()
    if not stripped.startswith("/"):
        return None

    head, _, tail = stripped.partition(" ")
    command_token = head[1:].strip()
    if not command_token:
        return None

    name = command_token.split("@", 1)[0].strip().lower()
    if not name:
        return None

    normalized_tail = tail.strip()
    normalized_text = f"/{name}"
    if normalized_tail:
        normalized_text += f" {normalized_tail}"

    return ParsedSlashCommand(
        name=name,
        args=normalized_tail.split() if normalized_tail else [],
        normalized_text=normalized_text,
    )


def _resolve_command_context(
    state: AppState,
    topic_id: Optional[int],
) -> tuple[CommandContext, object | None]:
    if state.is_global_topic(topic_id):
        return "global", None

    if topic_id is not None:
        ws = state.find_workspace_by_topic_id(topic_id)
        if ws is not None:
            return "workspace", ws

        found = state.find_thread_by_topic_id(topic_id)
        if found is not None:
            return "thread", found

    return "unknown", None


async def _invoke_local_handler(handler, update: Update, context, args: list[str]) -> None:
    previous_args = getattr(context, "args", None)
    context.args = list(args)
    try:
        await handler(update, context)
    finally:
        context.args = previous_args


async def _delegate_to_message_handler(
    message_handler,
    update: Update,
    context,
    normalized_text: str,
) -> None:
    message = update.effective_message
    if message is None:
        return

    class _MessageTextProxy:
        def __init__(self, raw_message, text: str):
            self._raw_message = raw_message
            self.text = text

        def __getattr__(self, name):
            return getattr(self._raw_message, name)

    class _UpdateMessageProxy:
        def __init__(self, raw_update, proxied_message):
            self._raw_update = raw_update
            self.effective_message = proxied_message

        def __getattr__(self, name):
            return getattr(self._raw_update, name)

    proxied_update = _UpdateMessageProxy(
        update,
        _MessageTextProxy(message, normalized_text),
    )
    await message_handler(proxied_update, context)


async def _maybe_open_thread_command_wrapper(
    state: AppState,
    group_chat_id: int,
    bot,
    message,
    parsed: ParsedSlashCommand,
    rule,
    resolved_target,
) -> bool:
    if rule is None or rule.telegram_behavior != "wrapper":
        return False
    if not isinstance(resolved_target, tuple) or len(resolved_target) != 2:
        return False

    ws_info, thread_info = resolved_target
    pending = await resolve_thread_command_wrapper(
        state,
        parsed.name,
        parsed.args,
        ws_info,
        thread_info,
    )
    if pending is None:
        return False

    wrapper_id = int(getattr(message, "message_id", 0) or 0)
    if wrapper_id <= 0:
        wrapper_id = int(time.time() * 1000)

    state.pending_command_wrappers[wrapper_id] = pending
    panel_message = await _send_to_group(
        bot,
        group_chat_id,
        pending.prompt_text,
        topic_id=getattr(message, "message_thread_id", None),
        parse_mode="Markdown",
        reply_markup=build_command_wrapper_keyboard(wrapper_id, pending.options),
    )
    panel_message_id = int(getattr(panel_message, "message_id", 0) or 0)
    if panel_message_id > 0:
        pending.panel_message_id = panel_message_id
    return True


def _scope_label(scope: CommandContext) -> str:
    if scope == "global":
        return "global topic"
    if scope == "workspace":
        return "workspace topic"
    if scope == "thread":
        return "thread topic"
    return "当前 topic"


def _provider_unavailable_message(cfg: Config | None, tool_name: str) -> str | None:
    if cfg is None:
        return None
    classification = classify_provider(tool_name, cfg)
    if classification in {"available", "hidden_provider"}:
        return None
    return provider_not_enabled_message(tool_name, classification)


async def _send_scope_rejection(
    bot,
    group_chat_id: int,
    topic_id: Optional[int],
    command_name: str,
    required_scope: CommandContext,
) -> None:
    await _send_to_group(
        bot,
        group_chat_id,
        f"`/{command_name}` 只能在 {_scope_label(required_scope)} 中使用。",
        topic_id=topic_id,
        parse_mode="Markdown",
    )


async def _send_thread_command_hint(
    bot,
    group_chat_id: int,
    topic_id: Optional[int],
    command_name: str,
) -> None:
    await _send_to_group(
        bot,
        group_chat_id,
        (
            f"`/{command_name}` 当前不在本区域执行。"
            "\n如果这是 provider slash command，请切到对应的 thread topic 再重试。"
            "\n可用 `/help` 查看当前区域命令。"
        ),
        topic_id=topic_id,
        parse_mode="Markdown",
    )


async def _send_tool_rejection(
    bot,
    group_chat_id: int,
    topic_id: Optional[int],
    command_name: str,
    required_tool: str,
) -> None:
    await _send_to_group(
        bot,
        group_chat_id,
        f"`/{command_name}` 当前只在 `{required_tool}` thread topic 中生效。",
        topic_id=topic_id,
        parse_mode="Markdown",
    )


async def _send_wrapper_capability_rejection(
    bot,
    group_chat_id: int,
    topic_id: Optional[int],
    command_name: str,
    supported_providers: list[str],
) -> None:
    if supported_providers:
        required_tool = " / ".join(supported_providers)
        await _send_tool_rejection(
            bot,
            group_chat_id,
            topic_id,
            command_name,
            required_tool,
        )
        return

    await _send_to_group(
        bot,
        group_chat_id,
        f"`/{command_name}` 当前没有可用的 TG wrapper provider。",
        topic_id=topic_id,
        parse_mode="Markdown",
    )


def make_slash_command_handler(
    state: AppState,
    group_chat_id: int,
    cfg: Config,
) -> Callable:
    message_handler = make_message_handler(state, group_chat_id)
    local_handlers = {
        "start": make_start_handler(group_chat_id),
        "ping": make_ping_handler(group_chat_id),
        "echo": make_echo_handler(group_chat_id),
        "help": make_help_handler(state, group_chat_id),
        "status": make_status_handler(state, group_chat_id),
        "active": make_active_handler(state, group_chat_id),
        "cli": make_cli_handler(state, group_chat_id, cfg),
        "workspace": make_workspace_handler(state, group_chat_id, cfg),
        "new": make_new_thread_handler(state, group_chat_id),
        "list": make_list_thread_handler(state, group_chat_id),
        "archive": make_archive_thread_handler(state, group_chat_id),
        "skills": make_skills_handler(state, group_chat_id),
        "history": make_history_handler(state, group_chat_id),
        "restart": make_restart_handler(group_chat_id),
        "stop": make_stop_handler(group_chat_id),
    }

    async def handle_slash(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        if message is None:
            return

        parsed = parse_slash_command(getattr(message, "text", None))
        if parsed is None:
            return

        canonical_name = resolve_registered_command_alias(parsed.name)
        if canonical_name != parsed.name:
            parsed = ParsedSlashCommand(
                name=canonical_name,
                args=parsed.args,
                normalized_text=f"/{canonical_name}" + (f" {' '.join(parsed.args)}" if parsed.args else ""),
            )

        topic_id = getattr(message, "message_thread_id", None)
        context_kind, resolved_target = _resolve_command_context(state, topic_id)
        logger.info(
            "[slash_router] cmd=%s context=%s normalized=%r",
            parsed.name,
            context_kind,
            parsed.normalized_text,
        )

        rule = get_command_rule(parsed.name)

        if context_kind == "thread":
            if isinstance(resolved_target, tuple) and len(resolved_target) == 2:
                ws_info, _thread_info = resolved_target
                unavailable = _provider_unavailable_message(cfg, getattr(ws_info, "tool", ""))
                if unavailable:
                    await _send_to_group(
                        context.bot,
                        group_chat_id,
                        f"❌ {unavailable}",
                        topic_id=topic_id,
                    )
                    return

            if (
                rule
                and rule.telegram_behavior == "wrapper"
                and isinstance(resolved_target, tuple)
                and len(resolved_target) == 2
            ):
                ws_info, _thread_info = resolved_target
                spec = get_interaction_spec(parsed.name)
                if spec is not None and not supports_thread_command_wrapper(ws_info.tool, parsed.name):
                    await _send_wrapper_capability_rejection(
                        context.bot,
                        group_chat_id,
                        topic_id,
                        parsed.name,
                        get_wrapper_supported_providers(parsed.name),
                    )
                    return

            if (
                rule
                and rule.tool_name is not None
                and isinstance(resolved_target, tuple)
                and len(resolved_target) == 2
            ):
                ws_info, _thread_info = resolved_target
                if getattr(ws_info, "tool", None) != rule.tool_name:
                    await _send_tool_rejection(
                        context.bot,
                        group_chat_id,
                        topic_id,
                        parsed.name,
                        rule.tool_name,
                    )
                    return

            if rule and rule.scope == "thread" and rule.executor == "bot":
                await _invoke_local_handler(
                    local_handlers[parsed.name],
                    update,
                    context,
                    parsed.args,
                )
                return

            if await _maybe_open_thread_command_wrapper(
                state,
                group_chat_id,
                context.bot,
                message,
                parsed,
                rule,
                resolved_target,
            ):
                return

            if rule and rule.scope == "workspace" and rule.scope_policy == "strict":
                await _send_scope_rejection(
                    context.bot,
                    group_chat_id,
                    topic_id,
                    parsed.name,
                    "workspace",
                )
                return

            if (
                rule
                and rule.scope == "workspace"
                and rule.scope_policy == "fallback"
                and rule.executor == "bot"
            ):
                await _invoke_local_handler(
                    local_handlers[parsed.name],
                    update,
                    context,
                    parsed.args,
                )
                return

            if rule and rule.scope == "global" and rule.scope_policy == "strict":
                await _send_scope_rejection(
                    context.bot,
                    group_chat_id,
                    topic_id,
                    parsed.name,
                    "global",
                )
                return

            if (
                rule
                and rule.scope == "global"
                and rule.executor == "bot"
                and not rule.thread_downstream_priority
            ):
                await _invoke_local_handler(
                    local_handlers[parsed.name],
                    update,
                    context,
                    parsed.args,
                )
                return

            if (
                rule
                and rule.scope == "contextual"
                and rule.executor in {"bot", "hybrid"}
                and not rule.thread_downstream_priority
            ):
                await _invoke_local_handler(
                    local_handlers[parsed.name],
                    update,
                    context,
                    parsed.args,
                )
                return

            await _delegate_to_message_handler(
                message_handler,
                update,
                context,
                parsed.normalized_text,
            )
            return

        if context_kind == "workspace":
            if resolved_target is not None:
                unavailable = _provider_unavailable_message(cfg, getattr(resolved_target, "tool", ""))
                if unavailable:
                    await _send_to_group(
                        context.bot,
                        group_chat_id,
                        f"❌ {unavailable}",
                        topic_id=topic_id,
                    )
                    return

            if rule and rule.scope == "thread":
                await _send_scope_rejection(
                    context.bot,
                    group_chat_id,
                    topic_id,
                    parsed.name,
                    "thread",
                )
                return

            if rule and rule.scope == "global" and rule.scope_policy == "strict":
                await _send_scope_rejection(
                    context.bot,
                    group_chat_id,
                    topic_id,
                    parsed.name,
                    "global",
                )
                return

            if (
                rule
                and (
                    rule.scope == "workspace"
                    or (rule.scope == "global" and rule.executor == "bot")
                    or rule.scope == "contextual"
                )
            ):
                await _invoke_local_handler(
                    local_handlers[parsed.name],
                    update,
                    context,
                    parsed.args,
                )
                return

            await _send_thread_command_hint(
                context.bot,
                group_chat_id,
                topic_id,
                parsed.name,
            )
            return

        if rule and rule.scope == "thread":
            await _send_scope_rejection(
                context.bot,
                group_chat_id,
                topic_id,
                parsed.name,
                "thread",
            )
            return

        if rule and rule.scope == "workspace":
            await _send_scope_rejection(
                context.bot,
                group_chat_id,
                topic_id,
                parsed.name,
                "workspace",
            )
            return

        if (
            rule
            and (
                rule.scope == "global"
                or rule.scope == "contextual"
            )
        ):
            await _invoke_local_handler(
                local_handlers[parsed.name],
                update,
                context,
                parsed.args,
            )
            return

        await _send_thread_command_hint(
            context.bot,
            group_chat_id,
            topic_id,
            parsed.name,
        )

    return handle_slash
