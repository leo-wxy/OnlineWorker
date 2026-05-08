# OnlineWorker — Agent 工作手册

本文件面向 AI coding agent（Claude、Codex 等），记录项目关键约定、打包规则和常用命令，**每次开始新会话前必须读这个文件**，避免反复犯同样的错误。

---

## 项目结构概览

```
onlineWorker/
├── main.py                     # Bot 入口
├── bot/                        # Telegram bot 逻辑
│   └── handlers/workspace.py   # Workspace 相关 handler
├── core/
│   └── lifecycle.py            # Bot 启动/初始化逻辑
├── mac-app/                    # Tauri Mac App
│   ├── src/                    # React 前端
│   └── src-tauri/              # Rust 后端
│       ├── binaries/           # sidecar binary 目录
│       ├── default-config.yaml # 默认配置（service 端口、TUI 主控策略、bot 默认行为等）
│       └── src/commands/service.rs  # service_start / service_stop
├── scripts/build.sh            # aarch64 完整打包脚本
├── onlineworker.spec           # aarch64 PyInstaller spec（不要修改）
├── onlineworker-x86_64.spec    # x86_64 PyInstaller spec
├── deploy/BUILD.md             # 打包详细文档
└── AGENTS.md                   # 本文件
```

---

## 关键约定（高优先级，不要违反）

### 1. Storage 路径

Bot 实际运行时读写的 storage 是 **CWD 下的 `onlineworker_state.json`**：

```
/path/to/onlineWorker/onlineworker_state.json
```

不是 `~/Library/Application Support/OnlineWorker/onlineworker_state.json`（那是 App 打包后的路径）。

调试时直接编辑 CWD 下的文件。

### 2. PyInstaller spec 文件

- `onlineworker.spec` — **专用于 arm64，不要修改**
- `onlineworker-x86_64.spec` — 专用于 x86_64，两者区别仅在 `target_arch`

### 3. 验收与测试基准

- **所有功能测试、联调验证和最终验收，一律以 OnlineWorker App（application 运行态）为准**
- **从本次起，后续所有测试流程一律在 App 内执行；不要再把命令行、脚本、`main.py`、`pnpm dev`、Tauri dev、单元测试当作正式测试流程**
- **本地包验收默认流程**：重新打包 → 覆盖 `/Applications/OnlineWorker.app` → 完全退出旧 App 进程 → 重新启动 App → 在 App 内验证；不要停留在“DMG 已生成”这一步
- **上面这 5 步必须完整闭环**。只完成“打包”或“覆盖”都不算验收完成；只看到 App 已打开也不算，必须明确完成旧 App 退出和新 App 重启。
- **覆盖安装后必须核验运行态确实切换到新版本**：至少检查 `onlineworker-app` 和 `onlineworker-bot --data-dir ~/Library/Application Support/OnlineWorker` 的新 PID / 新启动时间；不能只看到 App 已打开，就默认 sidecar 也已更新
- **若覆盖后旧进程仍存活，必须强制杀掉旧进程再重新打开 App**：重点检查并清理 `/Applications/OnlineWorker.app/Contents/MacOS/onlineworker-app` 与 `/Applications/OnlineWorker.app/Contents/MacOS/onlineworker-bot`；否则用户实际测到的仍可能是旧逻辑
- 命令行直跑 `main.py`、单元测试、脚本验证、日志检查，只能作为**辅助定位问题**的手段，不能作为“功能正常”或“修复完成”的最终依据
- 若需要用户配合验证，默认要求用户在 App 内操作；除非用户明确要求仅做源码态排查，否则不要引导用户走 CLI/脚本验证链路
- 只要改动影响 bot sidecar、Tauri 后端、前端交互、service start/stop、workspace/thread/topic 行为，就必须回到 App 内实际操作验证
- 如果目标是验证交付包行为，则必须基于重新打包后的 App 验证；不要用源码态运行结果替代安装包行为

### 4. TUI 主控 / TG 轻办公约定（2026-04-04）

- **默认主控界面是 App 内 TUI / Sessions**。长过程观察、上下文核对、人工接管和会话整理，都以 TUI 为准。
- **Telegram 只承担轻量远程入口**：发起任务、补充说明、审批、查看状态、接收最终回复。
- **不要再把“TG / TUI / CLI 实时逐条同步”当默认目标或验收标准**。默认只要求 TG 能把消息送进主会话，并收到基本完整的最终回复。
- **若 TG 没实时显示 TUI 中间过程，默认先不判定为故障**。先看完成态、失败态和审批态是否正确回到 TG。
- **codex 当前推荐形态是 `TUI 主控 + TG 最终回复模式`**：
  - App 负责确保 shared `codex app-server` 可用
  - TUI 是主要 live client
  - TG 发消息时按需短连注入，不再常驻保持第二条 live ws 连接
---

## 打包规则（关键，每次打包前必读）

> **黄金法则**：打包必须先用 PyInstaller 重新构建 bot binary，再打 tauri 包。  
> 直接跑 `pnpm tauri build` 不会重新编译 bot binary，包里会是旧代码。

### aarch64 (Apple Silicon) — 完整流程

```bash
export NVM_DIR="$HOME/.nvm" && source "$NVM_DIR/nvm.sh" && nvm use 20
cd /path/to/onlineWorker
bash scripts/build.sh
```

`scripts/build.sh` 自动完成：PyInstaller → copy sidecar → tauri build

产物：`mac-app/src-tauri/target/release/bundle/dmg/OnlineWorker_0.2.0_aarch64.dmg`

本地测试默认还要追加一步：把新生成的 App 覆盖安装到 `/Applications/OnlineWorker.app`，然后重启 App 再做验收。

### x86_64 (Intel) — 分步流程

**Step 1：构建 x86_64 bot binary**

```bash
cd /path/to/onlineWorker
arch -x86_64 /usr/local/bin/python3.13 -m PyInstaller onlineworker-x86_64.spec --clean --noconfirm --distpath dist-x86_64
cp dist-x86_64/onlineworker-bot mac-app/src-tauri/binaries/onlineworker-bot-x86_64-apple-darwin
```

**Step 2：打 tauri 包**

```bash
export NVM_DIR="$HOME/.nvm" && source "$NVM_DIR/nvm.sh" && nvm use 20
cd /path/to/onlineWorker/mac-app
pnpm tauri build --target x86_64-apple-darwin
```

产物：`mac-app/src-tauri/target/x86_64-apple-darwin/release/bundle/dmg/OnlineWorker_0.2.0_x64.dmg`

### 验证构建产物

```bash
# 检查 DMG 文件
ls -lh mac-app/src-tauri/target/release/bundle/dmg/*.dmg
ls -lh mac-app/src-tauri/target/x86_64-apple-darwin/release/bundle/dmg/*.dmg

# 检查 sidecar binary 架构（预期一个 arm64，一个 x86_64）
file mac-app/src-tauri/binaries/onlineworker-bot-*
```

---

## 常用命令

### 本地开发运行 Bot

```bash
cd /path/to/onlineWorker
nohup /path/to/python3 main.py >> "$HOME/Library/Application Support/OnlineWorker/onlineworker.log" 2>&1 &
```

> 必须用已安装依赖的 Python 运行时，系统自带的 `/opt/homebrew/bin/python3` 通常没有安装项目依赖包。

### 停止 Bot

```bash
pkill -f "python.*main.py"
```

### 查看运行日志

```bash
tail -f "$HOME/Library/Application Support/OnlineWorker/onlineworker.log"
```

### 本地开发运行 Mac App

```bash
cd mac-app
pnpm dev
```

---

## 已修复的 Bug（历史记录）

| Bug | 文件 | 说明 |
|-----|------|------|
| thread topic 重复创建 | `bot/handlers/workspace.py` | `_creating_topics` 并发保护缺失 |
| global topic 存活验证 | `core/lifecycle.py` | `post_init` 加全局 topic 存活验证 |
| service_stop 残留进程 | `mac-app/src-tauri/src/commands/service.rs` | 加 `pkill -9 -f onlineworker-bot` 兜底 |
| 新用户 bot 报 no listening url | `mac-app/src-tauri/default-config.yaml` | 确认默认端口配置正确，并由 bot 自己拉起服务 |
| provider 历史同步兼容问题 | 相关 provider runtime / adapter 文件 | 统一走当前 provider runtime 边界，避免把旧同步逻辑暴露到公开文档 |
| TG 图片消息 | `bot/handlers/message.py` / provider RPC | TG 图片按当前 provider 的远程消息协议转发，文件 part 使用 base64 data URL，caption 追加 text part |

---

## 注意事项

- **打包规则**：**只有用户明确允许时才可以打包**，不要自作主张打包浪费时间
- **本地验收规则**：只要用户目标是“验证新改动”，默认流程是“打包 + 覆盖 `/Applications/OnlineWorker.app` + 完全退出旧 App + 重新启动 App + 验证”；不要只停在 DMG 生成完成
- **运行态核验规则**：覆盖安装后，必须确认新的 `onlineworker-app` / `onlineworker-bot` 进程已经起来，且不是沿用旧 PID/旧启动时间；必要时先 `pkill -9` 旧进程，再重新打开 App
- 验收汇报时，必须明确说明这条链路是否完整执行完毕；如果少了任一步，只能标记为 `未完成验收`，不能说“已验证”。
- 修改 bot 代码后，打包前必须重新跑 PyInstaller，否则包里是旧代码
- 所有后续测试流程、功能验收和用户验证，一律走 App；源码态脚本、单测、日志仅用于辅助排查，不能替代测试流程
- `codex` 当前默认是 `TUI 主控 + TG 最终回复`。若用户需要移动办公找回上下文，优先补最终完整回复同步到 TG，不要先恢复全量流式或双 WS 常驻。
- token 不在 app 里，用户在 Setup 页面填写后保存到 `~/Library/Application Support/OnlineWorker/.env`
- x86_64 Python 路径：`/usr/local/bin/python3.13`（x86_64 Homebrew 安装）
- arm64 Python 路径：`~/.pyenv/versions/3.13.1/bin/python3`（pyenv 管理）
- 详细打包说明见 `deploy/BUILD.md`
