# Scripts

本目录保留公开可用的构建、运行和前置验证脚本。

## Build / packaging

- `build.sh`：Apple Silicon 基础完整打包脚本。按项目规则，只有用户明确允许打包时才执行。它默认只打包当前仓库内置的 providers。
- `build.sh` 额外支持 `ONLINEWORKER_PLUGIN_SOURCE_DIRS`，可在打包前把额外 provider 包 staged 到 bundle resource 目录。
- 如果你维护额外 provider 包，可在本地包装脚本里设置 `ONLINEWORKER_PLUGIN_SOURCE_DIRS=...` 后复用同一套 `build.sh`。
- `scripts/` 目录只保留当前仓库可复用的基础构建与诊断脚本，不维护仓库外部的包装逻辑。

## Runtime helpers

- `codex_tui_host.py`：Codex TUI host wrapper 的本地运行入口，仍被 TUI 主控链路使用。

## Smoke / diagnostics

- `claude_hook_smoke.py`：Claude hook smoke 脚本，已有 `tests/test_claude_hook_smoke.py` 保护。默认复用当前 Python 解释器；如需指定 bridge 解释器，可设置 `ONLINEWORKER_BRIDGE_PYTHON=/path/to/python`。
- `cleanup_smoke_sessions.py`：面向本地 `~/.codex` 和 `~/.claude` 存储的固定 smoke 清理脚本，用于归档 Codex smoke thread 并删除对应的本地 session 文件。
- `archive_roundtrip_check.py`：手动 archive 诊断脚本，会创建真实 codex thread；只在 archive 端到端链路排障时手工运行，不纳入日常回归。

## Excluded

- `__pycache__/` 与 `*.pyc` 是本地缓存，已由 repo `.gitignore` 排除，不属于 source cleanup 对象。
- 临时 PoC 如果已被主实现和测试覆盖，应删除或迁移到更合适的位置，不应长期留在本目录。
