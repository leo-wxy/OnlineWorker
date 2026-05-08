# OnlineWorker Mac App 打包指南

## 快速打包命令

### aarch64 (Apple Silicon) DMG

```bash
export NVM_DIR="$HOME/.nvm" && source "$NVM_DIR/nvm.sh" && nvm use 20 && cd /path/to/onlineWorker && bash scripts/build.sh
```

产物: `mac-app/src-tauri/target/release/bundle/dmg/OnlineWorker_0.2.0_aarch64.dmg`

### x86_64 (Intel) DMG

前提：`mac-app/src-tauri/binaries/onlineworker-bot-x86_64-apple-darwin` 已存在

```bash
export NVM_DIR="$HOME/.nvm" && source "$NVM_DIR/nvm.sh" && nvm use 20 && cd /path/to/onlineWorker/mac-app && pnpm tauri build --target x86_64-apple-darwin
```

产物: `mac-app/src-tauri/target/x86_64-apple-darwin/release/bundle/dmg/OnlineWorker_0.2.0_x64.dmg`

---

## 前置要求

1. **开发环境**
   - macOS 系统（建议 Apple Silicon 机器）
   - Node.js 20+ (通过 nvm 管理)
   - Python 3.13+ (通过 pyenv 管理)
   - Rust + Cargo (通过 rustup 管理)
   - pnpm 包管理器

2. **Rust 交叉编译 target**
   ```bash
   # 查看已安装的 target
   rustup target list | grep apple-darwin
   
   # 安装 aarch64 target (Apple Silicon)
   rustup target add aarch64-apple-darwin
   
   # 安装 x86_64 target (Intel)
   rustup target add x86_64-apple-darwin
   ```

3. **Python 环境**
   - arm64: `~/.pyenv/versions/3.13.1/bin/python3`（pyenv 管理）
   - x86_64: `/usr/local/bin/python3.13`（x86_64 Homebrew `/usr/local/bin/brew` 安装）
   
   ```bash
   # arm64 依赖
   pip install pyinstaller
   
   # x86_64 依赖（需要 --break-system-packages）
   arch -x86_64 /usr/local/bin/python3.13 -m pip install --break-system-packages \
     pyinstaller httpx websockets python-telegram-bot pyyaml python-dotenv
   ```

4. **私有 provider overlay（可选）**
   - 如果你需要在本地恢复私有 provider，请通过 `ONLINEWORKER_PROVIDER_OVERLAY` 挂载外置 overlay 目录。
   - 打包后的公开默认 App 不会自动包含该 overlay；它只在运行时按环境变量加载。

## 详细打包流程

### build.sh 做了什么

`scripts/build.sh` 会自动检测当前机器架构并构建对应版本：

1. 使用 PyInstaller 构建 Python bot binary (`dist/onlineworker-bot`)
2. 将 binary 复制为带 target-triple 后缀的 sidecar (`mac-app/src-tauri/binaries/onlineworker-bot-{target}`)
3. 使用 Tauri 构建 Mac App 并打包成 DMG

### x86_64 Python Bot Binary

在 Apple Silicon 上通过 Rosetta 2 + x86_64 版本的 Python 来构建。

**前置条件：安装 x86_64 Python 和依赖**

```bash
# 通过 x86_64 Homebrew (/usr/local) 安装 Python 3.13
arch -x86_64 /usr/local/bin/brew install python@3.13

# 安装 PyInstaller 和项目依赖
arch -x86_64 /usr/local/bin/python3.13 -m pip install --break-system-packages \
  pyinstaller httpx websockets python-telegram-bot pyyaml python-dotenv
```

**构建步骤**

```bash
cd /path/to/onlineWorker

# 1. 用 x86_64 Python 运行 PyInstaller（使用专用 spec 文件）
arch -x86_64 /usr/local/bin/python3.13 -m PyInstaller onlineworker-x86_64.spec --clean --noconfirm --distpath dist-x86_64

# 2. 复制到 sidecar 目录
cp dist-x86_64/onlineworker-bot mac-app/src-tauri/binaries/onlineworker-bot-x86_64-apple-darwin
```

> **注意**：`onlineworker-x86_64.spec` 与 `onlineworker.spec` 的区别仅在于 `target_arch='x86_64'`。不要修改 `onlineworker.spec`，它专用于 arm64。

## 验证构建产物

```bash
# 检查 DMG 文件
ls -lh mac-app/src-tauri/target/release/bundle/dmg/*.dmg
ls -lh mac-app/src-tauri/target/x86_64-apple-darwin/release/bundle/dmg/*.dmg

# 检查 sidecar binary 架构
file mac-app/src-tauri/binaries/onlineworker-bot-*
```

预期输出：
```
onlineworker-bot-aarch64-apple-darwin: Mach-O 64-bit executable arm64
onlineworker-bot-x86_64-apple-darwin: Mach-O 64-bit executable x86_64
```

## 常见问题

### DMG 打包失败：`bundle_dmg.sh` 错误

```bash
# 清理构建缓存后重试
cd mac-app/src-tauri
rm -rf target/*/release/bundle/dmg/rw.*.dmg
rm -rf target/*/release/bundle/dmg/bundle_dmg.sh
```

### PyInstaller 找不到依赖模块

```bash
pip install -r requirements.txt
rm -rf build dist __pycache__
pyinstaller onlineworker-bot.spec --clean
```

## 版本历史

- **v0.2.0** (2026-04-23)
  - 收口 codex 运行时标准化与语义事件流
  - 完成 App UI 统一 workbench 风格调整
  - 日志弹层已适配新的应用视觉体系

- **v0.1.0** (2026-04-01)
  - 支持 aarch64 和 x86_64 两个架构
  - DMG 大小：aarch64 ~18.2M, x86_64 ~19.0M
