# OnlineWorker

OnlineWorker 是一个面向 macOS 的 AI 编码工作区。Mac App 负责 Setup、Sessions、Commands 和服务生命周期的主要控制；Telegram 只作为远程入口，用于发起任务、补充上下文、处理审批、查看状态以及接收最终回复。

默认工作流是 **App / Sessions 作为主控制面 + Telegram 负责最终回复**。

English version: [README.md](README.md)

## 功能

- Mac App 负责 Setup、Dashboard、Sessions、Commands 和日志控制。
- Telegram 作为远程任务入口和最终状态回传通道。
- 基于 provider 的配置方式，支持已接入的 CLI 后端。
- 可在 App 内浏览会话并发送消息。
- 最终回复支持 Markdown 渲染。
- 通过 Tauri + PyInstaller 提供适合安装的 macOS 打包能力。

## 运行要求

- macOS
- Node.js 20
- Python 3.13
- Tauri 后端所需的 Rust 工具链
- Codex 工作流所需的 `codex` CLI
- Claude 工作流所需的 `claude` CLI

## 快速开始

1. 构建或下载 macOS 安装包。
2. 打开 DMG，并将 `OnlineWorker.app` 拖到 `/Applications`。
3. 如果 macOS 首次启动时拦截了应用，移除 quarantine 属性：

```bash
xattr -cr /Applications/OnlineWorker.app
```

4. 启动 `OnlineWorker.app`。

## 初始设置

1. 打开应用，进入 `Setup`。
2. 填写 Telegram 相关值：
   - `TELEGRAM_TOKEN`
   - `ALLOWED_USER_ID`
   - `GROUP_CHAT_ID`
3. 确认你要使用的 CLI 工具已经安装，并且在 `PATH` 中可见。
4. 如果你通过官方登录流程使用 Claude，先执行 `claude auth login`。
5. 回到 `Dashboard`，启动服务。

## 配置

已安装的应用会在以下位置读写用户数据：

```text
~/Library/Application Support/OnlineWorker/config.yaml
~/Library/Application Support/OnlineWorker/.env
```

从源码运行时，仓库根目录下也可能使用本地的 `config.yaml`、`.env` 和 `onlineworker_state.json`。

私有 provider 可以通过 `ONLINEWORKER_PROVIDER_OVERLAY` 外置挂载。这个环境变量可以指向单个文件，也可以指向一个目录；当它指向目录时，OnlineWorker 会扫描目录下的 `plugin.yaml`，并加载其中声明的 provider descriptor。这样公开仓库只保留 builtin providers，本地需要私有 provider 时再单独挂载。

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

cargo test --manifest-path mac-app/src-tauri/Cargo.toml --quiet

cd mac-app
node --test tests/*.test.mjs
pnpm build
```

`pnpm build` 可能会输出一个已有的 Vite chunk-size 警告。只要命令以 0 状态码退出，构建就是成功的。

## 构建

### Apple Silicon DMG

```bash
cd /path/to/onlineWorker
bash scripts/build.sh
```

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
