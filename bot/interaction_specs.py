from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from core.providers.registry import (
    get_provider,
    list_providers,
)
from core.state import AppState, PendingCommandWrapper
from core.storage import ThreadInfo, WorkspaceInfo

InteractionBackend = str
InteractionType = Literal["enum", "confirm", "text"]
InteractionArgMode = Literal["passthrough_if_args", "wrapper_if_empty"]
InteractionOptionsSource = Literal["static", "runtime"]


@dataclass(frozen=True)
class InteractionSpec:
    name: str
    backend: InteractionBackend
    interaction_type: InteractionType
    arg_mode: InteractionArgMode
    options_source: InteractionOptionsSource
    examples: tuple[str, ...] = ()


@dataclass(frozen=True)
class CommandWrapperDispatchRequest:
    command_text: str
    completion_text: str


INTERACTION_SPECS: dict[str, InteractionSpec] = {
    "model": InteractionSpec(
        name="model",
        backend="both",
        interaction_type="enum",
        arg_mode="wrapper_if_empty",
        options_source="runtime",
    ),
    "review": InteractionSpec(
        name="review",
        backend="both",
        interaction_type="text",
        arg_mode="wrapper_if_empty",
        options_source="static",
        examples=("HEAD~1", "main..feature", "--help"),
    )
}


def get_interaction_spec(name: str) -> InteractionSpec | None:
    return INTERACTION_SPECS.get(name.lower())


def supports_thread_command_wrapper(tool_name: str, command_name: str) -> bool:
    provider = get_provider(tool_name)
    if provider is None:
        return False
    wrappers = getattr(provider.capabilities, "command_wrappers", ())
    normalized = str(command_name or "").strip().lower()
    return normalized in {str(item).strip().lower() for item in wrappers}


def get_wrapper_supported_providers(command_name: str) -> list[str]:
    normalized = str(command_name or "").strip().lower()
    if not normalized:
        return []

    supported: list[str] = []
    for provider in list_providers():
        wrappers = getattr(provider.capabilities, "command_wrappers", ())
        if normalized in {str(item).strip().lower() for item in wrappers}:
            supported.append(provider.name)
    return supported


def _get_provider_command_hooks(tool_name: str):
    provider = get_provider(tool_name)
    return provider.command_hooks if provider is not None else None


def _build_text_command_text(command_name: str, text_value: str | None) -> str:
    suffix = (text_value or "").strip()
    return f"/{command_name}" if not suffix else f"/{command_name} {suffix}"


def _render_text_command_wrapper(
    spec: InteractionSpec,
    pending: PendingCommandWrapper,
) -> PendingCommandWrapper:
    from core.state import PendingCommandWrapperOption

    command_text = _build_text_command_text(pending.command_name, pending.text_value)
    examples = " / ".join(f"`{item}`" for item in spec.examples if item)
    lines = [f"`/{pending.command_name}` 参数面板", ""]

    if pending.awaiting_text or not (pending.text_value or "").strip():
        pending.awaiting_text = True
        pending.current_step = "await_text"
        pending.options = []
        lines.extend(
            [
                "第 1 步：请直接在当前 Topic 发送参数文本。",
                f"当前暂存参数：`{pending.text_value or '未填写'}`",
            ]
        )
        if examples:
            lines.append(f"示例：{examples}")
        lines.append("收到文本后，我会先给你确认，不会直接执行。")
    else:
        pending.awaiting_text = False
        pending.current_step = "confirm"
        pending.options = [
            PendingCommandWrapperOption(
                label="✏️ 重新输入参数",
                value="",
                action="collect_text",
            ),
            PendingCommandWrapperOption(
                label="✅ 确认执行",
                value="apply",
                action="apply",
            ),
        ]
        lines.extend(
            [
                "第 2 步：确认执行",
                f"已填写参数：`{pending.text_value}`",
                f"将执行：`{command_text}`",
                "确认后，会复用当前 thread 的真实发送链路下发。",
            ]
        )

    pending.prompt_text = "\n".join(lines)
    pending.interaction_type = spec.interaction_type
    return pending


def consume_command_wrapper_text_input(
    pending: PendingCommandWrapper,
    text: str,
) -> PendingCommandWrapper:
    spec = get_interaction_spec(pending.command_name)
    if spec is None or spec.interaction_type != "text":
        raise RuntimeError("当前命令不支持文本参数面板。")

    cleaned = str(text or "").strip()
    if not cleaned:
        raise RuntimeError("参数不能为空。")

    pending.text_value = cleaned
    pending.awaiting_text = False
    pending.current_step = "confirm"
    return _render_text_command_wrapper(spec, pending)


async def resolve_thread_command_wrapper(
    state: AppState,
    command_name: str,
    args: list[str],
    ws_info: WorkspaceInfo,
    thread_info: ThreadInfo,
) -> PendingCommandWrapper | None:
    spec = get_interaction_spec(command_name)
    if spec is None:
        return None
    if spec.arg_mode == "wrapper_if_empty" and args:
        return None
    if not supports_thread_command_wrapper(ws_info.tool, command_name):
        return None

    if spec.interaction_type == "text":
        pending = PendingCommandWrapper(
            command_name=command_name,
            workspace_id=ws_info.daemon_workspace_id or "",
            thread_id=thread_info.thread_id,
            topic_id=thread_info.topic_id,
            tool_name=ws_info.tool,
            prompt_text="",
            interaction_type="text",
            current_step="await_text",
            awaiting_text=True,
        )
        return _render_text_command_wrapper(spec, pending)

    command_hooks = _get_provider_command_hooks(ws_info.tool)
    build_wrapper = (
        getattr(command_hooks, "build_thread_command_wrapper", None)
        if command_hooks is not None
        else None
    )
    if not callable(build_wrapper):
        return None
    return await build_wrapper(state, command_name, args, ws_info, thread_info)


async def refresh_command_wrapper(
    state: AppState,
    pending: PendingCommandWrapper,
) -> PendingCommandWrapper:
    found = state.find_thread_by_id_global(pending.thread_id)
    if found is None:
        raise RuntimeError("当前 thread 已不存在，无法刷新命令面板。")

    ws_info, thread_info = found
    if not supports_thread_command_wrapper(ws_info.tool, pending.command_name):
        raise RuntimeError("当前命令暂时无法在此 thread 中刷新。")

    spec = get_interaction_spec(pending.command_name)
    if spec is not None and spec.interaction_type == "text":
        return _render_text_command_wrapper(spec, pending)

    command_hooks = _get_provider_command_hooks(ws_info.tool)
    refresh_wrapper = (
        getattr(command_hooks, "refresh_thread_command_wrapper", None)
        if command_hooks is not None
        else None
    )
    if callable(refresh_wrapper):
        refreshed = await refresh_wrapper(state, pending, ws_info, thread_info)
        refreshed.panel_message_id = pending.panel_message_id
        return refreshed

    refreshed = await resolve_thread_command_wrapper(
        state,
        pending.command_name,
        [],
        ws_info,
        thread_info,
    )
    if refreshed is None:
        raise RuntimeError("当前命令暂时无法在此 thread 中刷新。")
    return refreshed


async def apply_command_wrapper_selection(
    state: AppState,
    pending: PendingCommandWrapper,
    option_idx: int,
) -> PendingCommandWrapper | str | CommandWrapperDispatchRequest:
    tool_name = pending.tool_name or state.get_tool_for_workspace(pending.workspace_id) or ""
    if not tool_name:
        raise RuntimeError("当前命令面板缺少 provider 上下文。")
    if not supports_thread_command_wrapper(tool_name, pending.command_name):
        raise RuntimeError("当前命令未注册 TG wrapper 操作。")

    spec = get_interaction_spec(pending.command_name)
    if spec is not None and spec.interaction_type == "text":
        if option_idx < 0 or option_idx >= len(pending.options):
            raise RuntimeError("选项索引无效。")

        option = pending.options[option_idx]
        if option.action == "collect_text":
            pending.awaiting_text = True
            pending.current_step = "await_text"
            return _render_text_command_wrapper(spec, pending)
        if option.action == "apply":
            command_text = _build_text_command_text(pending.command_name, pending.text_value)
            if command_text == f"/{pending.command_name}":
                raise RuntimeError("请先输入命令参数。")
            return CommandWrapperDispatchRequest(
                command_text=command_text,
                completion_text=f"✅ 已发送：{command_text}",
            )
        raise RuntimeError("当前命令面板操作无效。")

    command_hooks = _get_provider_command_hooks(tool_name)
    apply_wrapper = (
        getattr(command_hooks, "apply_thread_command_wrapper_selection", None)
        if command_hooks is not None
        else None
    )
    if not callable(apply_wrapper):
        raise RuntimeError("当前命令未注册 TG wrapper 操作。")
    return await apply_wrapper(state, pending, option_idx)
