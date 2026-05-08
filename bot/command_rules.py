from dataclasses import dataclass
from typing import Literal

CommandExecutor = Literal["bot", "downstream", "hybrid"]
CommandScope = Literal["global", "workspace", "thread", "contextual"]
CommandScopePolicy = Literal["strict", "fallback", "contextual"]
TelegramBehavior = Literal["passthrough", "wrapper", "hidden"]
ToolName = str


@dataclass(frozen=True)
class CommandRule:
    name: str
    executor: CommandExecutor
    scope: CommandScope
    scope_policy: CommandScopePolicy
    telegram_behavior: TelegramBehavior = "passthrough"
    thread_downstream_priority: bool = False
    tool_name: ToolName | None = None


COMMAND_RULES: dict[str, CommandRule] = {
    "start": CommandRule(
        name="start",
        executor="bot",
        scope="global",
        scope_policy="fallback",
    ),
    "ping": CommandRule(
        name="ping",
        executor="bot",
        scope="global",
        scope_policy="fallback",
    ),
    "echo": CommandRule(
        name="echo",
        executor="bot",
        scope="global",
        scope_policy="fallback",
    ),
    "help": CommandRule(
        name="help",
        executor="hybrid",
        scope="contextual",
        scope_policy="contextual",
    ),
    "status": CommandRule(
        name="status",
        executor="hybrid",
        scope="contextual",
        scope_policy="contextual",
        thread_downstream_priority=True,
    ),
    "active": CommandRule(
        name="active",
        executor="bot",
        scope="global",
        scope_policy="fallback",
    ),
    "cli": CommandRule(
        name="cli",
        executor="bot",
        scope="global",
        scope_policy="strict",
    ),
    "workspace": CommandRule(
        name="workspace",
        executor="bot",
        scope="global",
        scope_policy="strict",
    ),
    "new": CommandRule(
        name="new",
        executor="bot",
        scope="workspace",
        scope_policy="fallback",
    ),
    "list": CommandRule(
        name="list",
        executor="bot",
        scope="workspace",
        scope_policy="fallback",
    ),
    "archive": CommandRule(
        name="archive",
        executor="bot",
        scope="thread",
        scope_policy="strict",
    ),
    "skills": CommandRule(
        name="skills",
        executor="bot",
        scope="thread",
        scope_policy="strict",
    ),
    "history": CommandRule(
        name="history",
        executor="bot",
        scope="thread",
        scope_policy="strict",
    ),
    "restart": CommandRule(
        name="restart",
        executor="bot",
        scope="global",
        scope_policy="fallback",
    ),
    "stop": CommandRule(
        name="stop",
        executor="bot",
        scope="global",
        scope_policy="fallback",
    ),
    "model": CommandRule(
        name="model",
        executor="downstream",
        scope="thread",
        scope_policy="strict",
        telegram_behavior="wrapper",
    ),
    "review": CommandRule(
        name="review",
        executor="downstream",
        scope="thread",
        scope_policy="strict",
        telegram_behavior="wrapper",
    ),
    "compact": CommandRule(
        name="compact",
        executor="downstream",
        scope="thread",
        scope_policy="strict",
    ),
    "permissions": CommandRule(
        name="permissions",
        executor="downstream",
        scope="thread",
        scope_policy="strict",
    ),
    "mcp": CommandRule(
        name="mcp",
        executor="downstream",
        scope="thread",
        scope_policy="strict",
    ),
    "search": CommandRule(
        name="search",
        executor="downstream",
        scope="thread",
        scope_policy="strict",
    ),
    "plan": CommandRule(
        name="plan",
        executor="downstream",
        scope="thread",
        scope_policy="strict",
    ),
}


def get_command_rule(name: str) -> CommandRule | None:
    return COMMAND_RULES.get(name.lower())
