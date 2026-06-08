# Scripts

本目录保留公开可用的构建、运行和前置验证脚本。

## Build / packaging

- `build.sh`：Apple Silicon 基础完整打包脚本。按项目规则，只有用户明确允许打包时才执行。它默认只打包当前仓库内置的 providers。
- `build.sh` 额外支持 `ONLINEWORKER_PLUGIN_SOURCE_DIRS`，可在打包前把额外 provider 包 staged 到 bundle resource 目录。
- 如果你维护额外 provider 包，可在本地包装脚本里设置 `ONLINEWORKER_PLUGIN_SOURCE_DIRS=...` 后复用同一套 `build.sh`。
- `scripts/` 目录只保留当前仓库可复用的基础构建与诊断脚本，不维护仓库外部的包装逻辑。
- `install-current-dmg.sh [path/to/OnlineWorker.dmg]`：不重新打包，直接安装最新或指定 DMG 到 `/Applications/OnlineWorker.app` 并重启。适合“DMG 已经打好，只要覆盖验证”的快路径；不替代发布前完整安装包验证链。
- `restart-installed-app.sh [/Applications/OnlineWorker.app]`：只重启已安装的 OnlineWorker App。脚本会把 stop、等待退出、open、等待 app/bot 新进程出现作为一个闭环执行，避免只杀进程没有拉起。
- `verify-packaged-fast.sh`：日常“开始验证”的推荐路径。它只做打包、覆盖 `/Applications/OnlineWorker.app`、重启并确认 app/bot 新进程存在，适合快速交给人工验证功能；发布、tag 或疑难排障时再跑完整安装包验证链。

## Verification shortcuts

- `verify-fast.sh`：并发运行常用回归检查，包括通知/配置相关 Python tests、App shell/tab 前端 tests、Rust `config_provider` tests 和前端 production build。它不打包、不覆盖安装，用于开发迭代阶段快速判断改动是否可继续。

## Runtime helpers

- `ow-codex`：Codex CLI remote proxy 包装脚本。文明模式当前已暂停，脚本仍保留为内部开发入口；验证 CLI 原生弹窗与 TG 同步授权时优先使用 OnlineWorker 主进程暴露的 Unix proxy socket：

  ```bash
  alias codexR='/opt/homebrew/bin/codex --remote "unix://$HOME/Library/Application Support/OnlineWorker/codex_remote_proxy.sock" --cd "$(pwd)"'
  ```

  不要用 `--remote unix://` 验证 OnlineWorker 审批链路；它连接的是 Codex 默认 socket，会绕过 OnlineWorker proxy。
- `ow-claude`：Claude CLI HTTP proxy 包装脚本。文明模式当前已封存，脚本仍可通过 `ANTHROPIC_BASE_URL` 把 Claude 请求导入本地代理并用 `--probe` 打印请求摘要，但不会改写 Anthropic `messages[].content` 用户文本；`--rewrite` / `--no-rewrite` 参数仅作为后续恢复链路的兼容保留项。若某个外部 launcher 会先运行自身逻辑再启动名为 `claude` 的二级进程，可显式传 `--launcher-wraps-claude --upstream-base-url <url>`，脚本会临时把 `claude` shim 放到 PATH 前面；具体 launcher 名称和 upstream 由用户配置提供，通用代码不内置私有命令或私有地址。
- `codex_tui_host.py`：Codex TUI host wrapper 的本地运行入口，仍被 TUI 主控链路使用。

## Smoke / diagnostics

- `claude_readiness_smoke.py`：Claude provider readiness 真实诊断脚本。它直接调用当前源码的 `ClaudeAdapter.check_readiness(force=True)`，可真实读取本机 `claude auth status` 与当前进程 `ANTHROPIC_*` runtime env，并读取 OnlineWorker `config.yaml` 中 Claude provider 当前配置的 `bin` 与可选 `launch_methods`。输出只包含 `ready/source/reason/authMethod/detail/apiProvider/launchMethod` 与 `methods[]` 里的非敏感候选方式，不打印 token 或原始 env。若用户显式配置多条 `launch_methods`，脚本会按顺序测试并标出最终选中的可用命令；未配置时保持单 `bin` 行为。`methods[]` 也会展示其他检测项，例如 `ow-claude` wrapper 文件存在但未配置为 provider bin 时只显示为候选，不会被误判成 provider 可发送。示例：

  ```bash
  python3 scripts/claude_readiness_smoke.py
  python3 scripts/claude_readiness_smoke.py --owner-bridge-status
  ```

  多启动方式使用 provider 通用 `launch_methods` 配置；只有声明
  `capabilities.launch_methods` 的 provider 会在 Settings 卡片里显示
  启动命令候选编辑区。Claude 当前声明了该能力，示例配置如下：

  ```yaml
  providers:
    claude:
      bin: "claude"
      launch_methods:
      - id: native
        label: Native Claude
        bin: "claude"
      - id: launcher
        label: Launcher Claude
        bin: "~/bin/claude-launcher claude"
  ```

- `claude_hook_smoke.py`：Claude hook smoke 脚本，已有 `tests/test_claude_hook_smoke.py` 保护。默认复用当前 Python 解释器；如需指定 bridge 解释器，可设置 `ONLINEWORKER_BRIDGE_PYTHON=/path/to/python`。
- `archive_roundtrip_check.py`：手动 archive 诊断脚本，会创建真实 codex thread；只在 archive 端到端链路排障时手工运行，不纳入日常回归。

## Excluded

- `__pycache__/` 与 `*.pyc` 是本地缓存，已由 repo `.gitignore` 排除，不属于 source cleanup 对象。
- 临时 PoC 如果已被主实现和测试覆盖，应删除或迁移到更合适的位置，不应长期留在本目录。
