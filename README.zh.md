# OnlineWorker

<p align="center">
  <img src="./launcher.png" alt="OnlineWorker 头图" width="360" />
</p>

OnlineWorker 是一个面向 macOS、本地 CLI agent 的 AI 编码工作区。Mac App 负责 Setup、Sessions、Commands、日志和服务生命周期的主要控制；Telegram 只作为远程入口，用于发起任务、补充上下文、处理审批、查看状态以及接收最终回复。

默认工作流是 **App / Sessions 作为主控制面 + Telegram 负责最终回复**。

English version: [README.md](README.md)

另见：

- [Documentation Notes](docs/README.md)
- [Contributing](CONTRIBUTING.md)
- [Security Policy](SECURITY.md)
- [Support](SUPPORT.md)

## 产品导览

以下截图基于真实 App UI 和脱敏 demo 数据生成，不包含真实 token、用户 ID、
本机路径、会话内容或私有扩展配置。

### Dashboard

<p align="center">
  <img src="./docs/screenshots/dashboard.png" alt="OnlineWorker 总览页" width="88%" />
</p>

Dashboard 是日常控制面。这里可以查看服务状态、provider 健康状态、最近活动，并快速进入 Setup、Sessions、日志、命令和用量页面。

### Sessions

<p align="center">
  <img src="./docs/screenshots/sessions-overview.png" alt="OnlineWorker 会话页" width="88%" />
</p>

Sessions 是主要工作面。你可以浏览 provider 会话，按 Active / Archived 过滤，打开会话，发送文本和图片/文件附件，并通过 provider-backed 动作归档会话。

### Usage

<p align="center">
  <img src="./docs/screenshots/usage.png" alt="OnlineWorker 用量页" width="88%" />
</p>

Usage 页面通过 provider metadata 和 usage hooks 读取用量。它支持 provider 切换、默认近 7 天窗口、日期筛选、汇总卡和每日图表，同时避免把 provider-specific 解析逻辑硬编码到 React 页面里。

### AI 服务与场景

<p align="center">
  <img src="./docs/screenshots/ai-services.png" alt="OnlineWorker AI 服务配置" width="88%" />
</p>

<p align="center">
  <img src="./docs/screenshots/ai-scenarios.png" alt="OnlineWorker AI 场景配置" width="88%" />
</p>

AI 页面把可复用的服务凭据和具体场景 prompt 分开。内置服务类型包括 OpenAI-compatible chat completions 和 Claude-compatible messages。通知完成摘要是第一个内置场景；当 AI 未启用、配置无效或调用失败时，会回退到确定性的本地摘要规则。

### Setup

<p align="center">
  <img src="./docs/screenshots/setup.png" alt="OnlineWorker 设置页" width="88%" />
</p>

Setup 处理首次运行时最实际的检查：必要 CLI 是否可见、Telegram 是否连通、服务生命周期是否正常，以及 App 成为主控制面前需要写入的配置。

## 核心能力

- 一个运行和监管本地 AI 编码 CLI 的 macOS 桌面工作区。
- 核心形态是已安装的 App；Telegram 是轻量远程入口，负责任务提交、补充上下文、审批、状态和最终回复。
- 当前仓库内置 provider 为 `codex` 和 `claude`；外部 provider 可通过公开插件契约挂载。
- 当前仓库内置通知渠道为 `telegram`；外部通知渠道可通过通知插件契约挂载。
- 基于 provider 的配置方式，支持已接入的 CLI 后端。
- Telegram 会镜像 provider 的审批和问题交互。Codex 审批只走 app-server
  request/response 链路，Telegram 按钮只负责回复该 server request。
- 基于插件的通知渠道，可在一级 `Notifications / 通知` 页面中配置。
- 最终回复支持 Markdown 渲染。
- 通过 Tauri + PyInstaller 提供适合安装的 macOS 打包能力。

## 安装与设置

### 运行要求

- macOS
- Node.js 20
- Python 3.13
- Tauri 后端所需的 Rust 工具链
- Codex 工作流所需的 `codex` CLI
- Claude 工作流所需的 `claude` CLI

### 快速开始

1. 本地构建 DMG，或直接下载打包好的 DMG。
2. 打开 DMG，并将 `OnlineWorker.app` 拖到 `/Applications`。
3. 如果 macOS 首次启动时拦截了应用，移除 quarantine 属性：

```bash
xattr -cr /Applications/OnlineWorker.app
```

4. 启动 `OnlineWorker.app`。

### 初始设置

1. 打开应用，进入 `Setup`。
2. 确认你要使用的 CLI 工具已经安装，并且在 `PATH` 中可见。
3. 填写 Telegram 相关值：
   - `TELEGRAM_TOKEN`
   - `ALLOWED_USER_ID`
   - `GROUP_CHAT_ID`
4. 如果你通过官方登录流程使用 Claude，先执行 `claude auth login`。如果你使用自定义上游或 launcher，就直接在 `Setup` 里的 Claude provider 卡片里填配置，不要手动改 env 文件。
5. 在 `Setup` 页用内置连通性检查确认 Telegram 访问正常。
6. 回到 `Dashboard`，启动服务。

### 配置

已安装的应用会在以下位置读写用户数据：

```text
~/Library/Application Support/OnlineWorker/config.yaml
~/Library/Application Support/OnlineWorker/.env
~/Library/Application Support/OnlineWorker/im_routes.sqlite3
```

从源码运行时，仓库根目录下也可能使用本地的 `config.yaml`、`.env` 和
`onlineworker_state.json`。正常使用时，建议通过 App 内设置界面修改配置。

`.env` 保存 Telegram 启动所需的基础值：

```bash
TELEGRAM_TOKEN=your_bot_token_here
ALLOWED_USER_ID=123456789
GROUP_CHAT_ID=-1001234567890
```

Claude 可以直接在 `Setup` 里的 Claude provider 卡片配置：

- `Claude Auth Token` 映射到 `ANTHROPIC_AUTH_TOKEN`
- `Claude Base URL` 映射到 `ANTHROPIC_BASE_URL`
- `Claude Model` 映射到 `ANTHROPIC_MODEL`

OnlineWorker 会把这些值写入 `config.yaml` 中 Claude provider 的
`external_cli` 段，再在 Claude 运行时注入到环境变量里；如果当前进程已经
有同名环境变量，就优先保留现有值。这样既能支持 packaged app 自己保存
配置，也能保留 shell 级覆盖。`Launcher wraps Claude` 开关适用于最终还是
会调用 `claude` 的 wrapper 启动器。

`config.yaml` 保存 provider、Telegram、通知渠道和 AI 服务/场景配置。
provider overlay 可通过 `ONLINEWORKER_PROVIDER_OVERLAY` 挂载；notification
overlay 可通过 `ONLINEWORKER_NOTIFICATION_OVERLAY` 挂载。

`im_routes.sqlite3` 保存外部 IM 入口到 OnlineWorker 内部固定目标的路由绑定。
内部目标只分为 `agent`、`workspace`、`session`；Telegram topic、Slack
thread、飞书群聊或其他 IM 入口只是外部 entry。`onlineworker_state.json`
里的 `topic_id` 字段只作为兼容镜像，运行时路由以 `im_routes.sqlite3` 为准。
未知 IM 入口会被记录为 `unknown`，但不会回退到当前 active workspace/session。

## 运行模型

### Provider 交互

OnlineWorker 会把 provider 审批和问题提示统一呈现在 App / Telegram
链路中。Codex 审批只接受 app-server server request，Telegram 按钮点击后
通过 `reply_server_request(...)` 回写该 request。

### Codex 文本发送

文明模式已暂时关闭，App 和 Telegram 都会原样发送用户输入。相关设置入口
不会在 App 中展示。

### Codex Unix remote proxy

Codex 使用 `protocol: unix` 时，OnlineWorker 会在 Codex app-server 之外再
启动一个受管理的本地 Unix socket proxy：

```bash
unix://~/Library/Application Support/OnlineWorker/codex_remote_proxy.sock
```

外部 Codex CLI 需要连接这个 OnlineWorker proxy，而不是直接连接 Codex
默认 app-server socket。推荐本机 alias：

```bash
alias codexR='/opt/homebrew/bin/codex --remote "unix://$HOME/Library/Application Support/OnlineWorker/codex_remote_proxy.sock" --cd "$(pwd)"'
```

固定 session 诊断时建议显式 resume，避免创建额外 session：

```bash
/opt/homebrew/bin/codex resume --remote "unix://$HOME/Library/Application Support/OnlineWorker/codex_remote_proxy.sock" --cd "$(pwd)" <session-id>
```

`--remote unix://` 会连接 Codex 默认 socket
`~/.codex/app-server-control/app-server-control.sock`，它会绕过 OnlineWorker；
这种连接只能让 OnlineWorker 看到 session 状态变化，拿不到需要回复的
approval server request，因此 Telegram 按钮不能接管审批。

OnlineWorker proxy 会：

- 转发 Codex CLI 与上游 app-server 的 remote 消息；
- 捕获 `execCommandApproval`、`applyPatchApproval` 和 `item/*/requestApproval`；
- 将已绑定 session 的审批推送到对应 Telegram topic；
- 根据 Telegram 按钮结果回写上游 app-server；
- 找不到 session/topic 或 Telegram 上下文不可用时，透传给原生 CLI 审批兜底。

proxy socket 和其父目录会分别设置为 `0600` / `0700`，限制在当前用户范围内。

### 会话操作

Sessions 页面支持浏览、发送消息、按 Active/Archived 过滤，以及归档具体会话。归档是 provider-backed 操作：OnlineWorker 会先调用 provider 的真实归档路径，成功后才更新本地状态；如果 provider 返回失败，本地会话状态保持不变。

Active workspace 下的 `New` 入口会打开首条消息输入区，而不是先创建本地
placeholder 会话。发送首条消息时，OnlineWorker 会先请求 provider 创建真实
session，再把消息发送到这个 provider thread。Codex 的 `thread/start` 较慢时，
UI 可能先收到 pending 结果；后台会继续等待 app-server notification 返回真实
thread id，并在活动流出现匹配的 provider-backed session 后选中这个真实会话，
同时保留界面上的乐观用户消息。本地 `app:*` draft id 不会作为会话展示。

### 用量

用量数据通过 provider metadata 和 usage hooks 暴露。App 的 Usage 页面会动态展示支持用量读取的 provider，新 provider 不需要把解析逻辑硬编码到 React 页面里。

Telegram 侧也提供 `/token_usage` 本地命令。这个命令只在 agent topic 中由 OnlineWorker 自己处理，不会发送给当前会话。具体 session topic 中使用时会收到拒绝提示，因为用量信息在 agent/provider topic 维度更有意义。

### AI 场景

AI 层是 OnlineWorker 的通用能力，不是 provider session。通知完成摘要会在启用且配置正确时使用 `notification_summary` 场景；否则 OnlineWorker 会回退到本地摘要规则。

## 开发

### 从源码运行 bot

```bash
cd /path/to/onlineWorker
/path/to/python3 main.py
```

源码模式现在默认使用与安装包一致的稳定数据目录。
只有在你明确需要隔离运行态时，才使用 `--data-dir /custom/path` 覆盖。

### 以开发模式运行 Mac App

```bash
cd /path/to/onlineWorker/mac-app
pnpm dev
```

### 运行测试

```bash
/path/to/python3 -m pytest -q tests/test_config.py tests/test_provider_facts.py tests/test_state.py tests/test_session_events.py

bash scripts/bootstrap-sidecar.sh
cargo test --manifest-path mac-app/src-tauri/Cargo.toml --quiet

cd mac-app
node --test tests/*.test.mjs
pnpm build
```

`pnpm build` 可能会输出一个已有的 Vite chunk-size 警告。只要命令以 0 状态码退出，构建就是成功的。

`scripts/bootstrap-sidecar.sh` 会创建一个被 Git 忽略的本地 sidecar 占位文件，用于满足 Tauri 源码态测试的构建元数据检查。它只用于源码测试；正式打包前，`scripts/build.sh` 会用真实 PyInstaller sidecar 覆盖它。

## 构建

### Apple Silicon DMG

```bash
cd /path/to/onlineWorker
bash scripts/build.sh
```

这条构建链路打包的是当前仓库里的基础 App。额外 provider 扩展包可以在运行态通过 `ONLINEWORKER_PROVIDER_OVERLAY` 挂载，额外通知渠道可以通过 `ONLINEWORKER_NOTIFICATION_OVERLAY` 挂载；provider 扩展包也可以在调用同一个 `scripts/build.sh` 前通过 `ONLINEWORKER_PLUGIN_SOURCE_DIRS` 做打包注入。

推送版本 tag（例如 `1.2.1`）也会通过 `.github/workflows/release-dmg.yml` 自动构建同一条 Apple Silicon DMG 链路。workflow 会先上传一份 Actions artifact；如果对应 GitHub Release 不存在，会先自动创建，再把 DMG 追加到该 Release 的资产列表。

如果本地 DMG 已经构建完成，可以用下面的脚本覆盖安装到
`/Applications`、重启打包 App，并确认 app/bot 进程都已启动：

```bash
bash scripts/install-current-dmg.sh mac-app/src-tauri/target/release/bundle/dmg/OnlineWorker_1.2.1_aarch64.dmg
```

如果只需要重启已安装的 App，不重新安装 DMG：

```bash
bash scripts/restart-installed-app.sh
```

### Intel DMG

Intel 打包流程见 [deploy/BUILD.md](deploy/BUILD.md)。

## 仓库结构

```text
onlineWorker/
├── main.py                  # bot 入口
├── bot/                     # Telegram bot handlers 与工具
├── core/                    # 共享 runtime、state、storage 与 provider contract
├── mac-app/                 # Tauri + React Mac App
├── plugins/                 # provider 与 notification plugin 描述/runtime 实现
├── scripts/                 # 构建与维护脚本
├── tests/                   # Python 测试
├── deploy/                  # 打包与部署说明
└── README.md
```

## 说明

- 源码模式主要用于开发和排障。
- 安装后的应用验证，始终应以打包后的 App 为准。

## 许可证

MIT。详见 [LICENSE](LICENSE)。
