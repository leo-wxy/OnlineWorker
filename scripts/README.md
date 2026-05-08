# Scripts

本目录保留公开可用的构建、运行和前置验证脚本。

## Build / packaging

- `build.sh`：Apple Silicon 完整打包脚本。按项目规则，只有用户明确允许打包时才执行。

## Runtime helpers

- `codex_tui_host.py`：Codex TUI host wrapper 的本地运行入口，仍被 TUI 主控链路使用。

## Smoke / diagnostics

- `claude_hook_smoke.py`：Claude hook smoke 脚本，已有 `tests/test_claude_hook_smoke.py` 保护。
- `provider_smoke.py`：固定 session 的 provider smoke 脚本，基于仓库根目录复用 `codex / claude` 会话，验证消息收发与权限回填。
- `provider_smoke.py --action archive`：归档并清理固定 smoke session，用于把已污染的测试线程收口。
- `archive_live_verify.py`：手动 archive 联调诊断脚本，会创建真实 codex thread；只在 archive 链路排障时手工运行，不纳入日常回归。

## Excluded

- `__pycache__/` 与 `*.pyc` 是本地缓存，已由 repo `.gitignore` 排除，不属于 source cleanup 对象。
- 临时 PoC 如果已被主实现和测试覆盖，应删除或迁移到更合适的位置，不应长期留在本目录。
