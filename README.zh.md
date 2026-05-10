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

## 截图

<p align="center">
  <img src="./docs/screenshots/dashboard.png" alt="OnlineWorker 总览页" width="49%" />
  <img src="./docs/screenshots/setup.png" alt="OnlineWorker 设置页" width="49%" />
</p>

## 概览

- 一个运行和监管本地 AI 编码 CLI 的 macOS 桌面工作区。
- 核心形态是已安装的 App，不是托管在浏览器里的服务。
- App 负责配置和日常控制，Telegram 负责远程输入和最终回传。
- 当前仓库内置的 provider 只有 `codex` 和 `claude`。

## 功能

- Mac App 负责 Setup、Dashboard、Sessions、Commands 和日志控制。
- Telegram 作为远程任务入口和最终状态回传通道。
- 基于 provider 的配置方式，支持已接入的 CLI 后端。
- 可在 App 内浏览会话并发送消息。
- 最终回复支持 Markdown 渲染。
- 通过 Tauri + PyInstaller 提供适合安装的 macOS 打包能力。

## Provider 范围

当前仓库内置支持的 provider 只有：

- `codex`
- `claude`

应用仍然支持通过公开插件契约挂载外部 provider 扩展包，但这个仓库只分发上面列出的 builtin providers。

## 运行要求

- macOS
- Node.js 20
- Python 3.13
- Tauri 后端所需的 Rust 工具链
- Codex 工作流所需的 `codex` CLI
- Claude 工作流所需的 `claude` CLI

## 快速开始

1. 本地构建 DMG，或直接下载打包好的 DMG。
2. 打开 DMG，并将 `OnlineWorker.app` 拖到 `/Applications`。
3. 如果 macOS 首次启动时拦截了应用，移除 quarantine 属性：

```bash
xattr -cr /Applications/OnlineWorker.app
```

4. 启动 `OnlineWorker.app`。

## 初始设置

1. 打开应用，进入 `Setup`。
2. 确认你要使用的 CLI 工具已经安装，并且在 `PATH` 中可见。
3. 填写 Telegram 相关值：
   - `TELEGRAM_TOKEN`
   - `ALLOWED_USER_ID`
   - `GROUP_CHAT_ID`
4. 如果你通过官方登录流程使用 Claude，先执行 `claude auth login`。
5. 在 `Setup` 页用内置连通性检查确认 Telegram 访问正常。
6. 回到 `Dashboard`，启动服务。

## 配置

已安装的应用会在以下位置读写用户数据：

```text
~/Library/Application Support/OnlineWorker/config.yaml
~/Library/Application Support/OnlineWorker/.env
```

从源码运行时，仓库根目录下也可能使用本地的 `config.yaml`、`.env` 和 `onlineworker_state.json`。

额外 provider 扩展包可以通过 `ONLINEWORKER_PROVIDER_OVERLAY` 外置挂载。这个环境变量可以指向单个文件，也可以指向一个目录；当它指向目录时，OnlineWorker 会扫描目录下的 `plugin.yaml`，并加载其中声明的 provider descriptor。已安装的 App 也会从 `~/Library/Application Support/OnlineWorker/.env` 读取同名 key；如果进程环境变量和 `.env` 同时存在，进程环境变量优先。

### `.env`

```bash
TELEGRAM_TOKEN=your_bot_token_here
ALLOWED_USER_ID=123456789
GROUP_CHAT_ID=-1001234567890

# 可选的 Claude 代理 / API 配置。
# 如果使用标准 CLI 登录流程，这些值可以留空。
ANTHROPIC_API_KEY=
ANTHROPIC_BASE_URL=
ANTHROPIC_MODEL=
```

### `config.yaml`

`config.yaml` 是应用的 provider 与 Telegram 配置文件。正常使用时，建议通过 App 内的设置界面修改。

## 开发

### 从源码运行 bot

```bash
cd /path/to/onlineWorker
/path/to/python3 main.py
```

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

这条构建链路打包的是当前仓库里的基础 App。额外 provider 扩展包可以在运行态通过 `ONLINEWORKER_PROVIDER_OVERLAY` 挂载，或者在调用同一个 `scripts/build.sh` 前通过 `ONLINEWORKER_PLUGIN_SOURCE_DIRS` 做打包注入。

### Intel DMG

```bash
cd /path/to/onlineWorker
arch -x86_64 /usr/local/bin/python3.13 -m PyInstaller onlineworker-x86_64.spec --clean --noconfirm --distpath dist-x86_64
cp dist-x86_64/onlineworker-bot mac-app/src-tauri/binaries/onlineworker-bot-x86_64-apple-darwin

cd mac-app
pnpm tauri build --target x86_64-apple-darwin
```

## 仓库结构

```text
onlineWorker/
├── main.py                  # bot 入口
├── bot/                     # Telegram bot handlers 与工具
├── core/                    # 共享 runtime、state、storage 与 provider contract
├── mac-app/                 # Tauri + React Mac App
├── plugins/                 # provider 描述与 runtime 实现
├── scripts/                 # 构建与维护脚本
├── tests/                   # Python 测试
├── deploy/                  # 打包与部署说明
└── README.md
```

## 说明

- 源码模式主要用于开发和排障。
- 安装后的应用验证，始终应以打包后的 App 为准。
- `__pycache__`、`.pytest_cache`、构建产物、`onlineworker_state.json` 等本地生成文件应保持未跟踪状态。

## 许可证

MIT。详见 [LICENSE](LICENSE)。
