# OnlineWorker Mac App 打包指南

## 快速打包命令

### aarch64 (Apple Silicon) DMG

```bash
export NVM_DIR="$HOME/.nvm" && source "$NVM_DIR/nvm.sh" && nvm use 20 && cd /path/to/OnlineWorker && bash scripts/build.sh
```

产物目录：`mac-app/src-tauri/target/release/bundle/dmg/`。文件名中的版本号来自 `mac-app/package.json`，当前为 `1.10.0`。

> 说明：这条命令对应当前仓库的基础构建路径。额外 provider 扩展包不会自动被打进这个 DMG；如果你需要把扩展包一起打包，请在调用 `scripts/build.sh` 前设置 `ONLINEWORKER_PLUGIN_SOURCE_DIRS`。

### GitHub Tag 自动打包

仓库内置了 GitHub Actions workflow：`.github/workflows/release-dmg.yml`。

- 触发方式：
  - 推送版本 tag（例如 `1.10.0`）后自动执行
  - 手动 `workflow_dispatch`，并传入一个已存在的 `release_tag`
- 运行环境：
  - `macos-15`
- 构建入口：
  - 直接复用仓库根目录的 `bash scripts/build.sh`
- 产物处理：
  - 先作为 Actions artifact 上传
  - 如果对应 GitHub Release 不存在，先自动创建
  - 再追加上传到对应的 GitHub Release 资产列表

当前 CI 只构建 **Apple Silicon / aarch64** DMG，不包含 Intel DMG，也不包含签名或 notarization。

### x86_64 (Intel) DMG

前提：以下两个 x86_64 sidecar 已存在：

- `mac-app/src-tauri/binaries/onlineworker-bot-x86_64-apple-darwin`
- `mac-app/src-tauri/binaries/ccusage-x86_64-apple-darwin`

```bash
export NVM_DIR="$HOME/.nvm" && source "$NVM_DIR/nvm.sh" && nvm use 20 && cd /path/to/OnlineWorker/mac-app && npm run tauri -- build --target x86_64-apple-darwin
```

产物目录：`mac-app/src-tauri/target/x86_64-apple-darwin/release/bundle/dmg/`。

---

## 前置要求

1. **开发环境**
   - macOS 系统（建议 Apple Silicon 机器）
   - Node.js 20+ (通过 nvm 管理)
   - Python 3.13+ (通过 pyenv 管理)
   - Rust + Cargo (通过 rustup 管理)
   - npm（随 Node.js 安装）
   - 已初始化 Git submodule：`git submodule update --init --recursive`

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
   - arm64: 你的本机 Python 3.13 环境（例如 pyenv 管理的 `python3`）
   - x86_64: `/usr/local/bin/python3.13`（x86_64 Homebrew `/usr/local/bin/brew` 安装）
   
   ```bash
   # arm64 依赖
   pip install pyinstaller
   
   # x86_64 依赖（需要 --break-system-packages）
   arch -x86_64 /usr/local/bin/python3.13 -m pip install --break-system-packages \
     pyinstaller httpx websockets python-telegram-bot pyyaml python-dotenv
   ```

4. **外部 provider 扩展包（可选）**
   - 如果你需要在本地挂载额外 provider，可通过 `ONLINEWORKER_PROVIDER_OVERLAY` 指向外部扩展包目录。
   - 如果你需要把额外 provider 一起打进 App，可在调用 `scripts/build.sh` 前设置 `ONLINEWORKER_PLUGIN_SOURCE_DIRS`。

## 详细打包流程

### build.sh 做了什么

`scripts/build.sh` 会同步应用版本，然后自动检测当前机器架构并执行四个构建阶段：

1. 使用 PyInstaller 构建 Python bot binary (`dist/onlineworker-bot`)
2. 将 binary 复制为带 target-triple 后缀的 sidecar (`mac-app/src-tauri/binaries/onlineworker-bot-{target}`)
3. 构建并复制仓库锁定版本的 `ccusage` sidecar (`mac-app/src-tauri/binaries/ccusage-{target}`)
4. 使用 Tauri 构建 Mac App 并打包成 DMG

### 基础构建 / 扩展构建

- **基础构建**：直接在 `OnlineWorker` 仓库里执行 `scripts/build.sh`。产物只包含当前仓库自带的 builtin providers。
- **扩展构建**：在你自己的本地包装脚本里先准备额外 provider 扩展包，再通过 `ONLINEWORKER_PLUGIN_SOURCE_DIRS` 调用同一套 `scripts/build.sh`。

两种样式最终都输出同一个 `OnlineWorker.app`。差异只存在于 build input，不存在于 bundle identity。

下游工作区可以按自己的需要组织。一个最小包装脚本只需要在调用 `scripts/build.sh` 前导出扩展包目录，例如：

```bash
export ONLINEWORKER_PLUGIN_SOURCE_DIRS="/path/to/provider-a:/path/to/provider-b"
bash scripts/build.sh
```

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
cd /path/to/OnlineWorker

# 1. 用 x86_64 Python 运行 PyInstaller（使用专用 spec 文件）
arch -x86_64 /usr/local/bin/python3.13 -m PyInstaller onlineworker-x86_64.spec --clean --noconfirm --distpath dist-x86_64

# 2. 复制 bot sidecar
cp dist-x86_64/onlineworker-bot mac-app/src-tauri/binaries/onlineworker-bot-x86_64-apple-darwin

# 3. 构建并复制 ccusage sidecar
CCUSAGE_PRICING_JSON_PATH="$PWD/third_party/ccusage-pricing.json" \
  cargo build --manifest-path third_party/ccusage/rust/crates/ccusage/Cargo.toml \
  --release --locked --target x86_64-apple-darwin
cp third_party/ccusage/rust/target/x86_64-apple-darwin/release/ccusage \
  mac-app/src-tauri/binaries/ccusage-x86_64-apple-darwin
```

> **注意**：`onlineworker-x86_64.spec` 与 `onlineworker.spec` 的区别仅在于 `target_arch='x86_64'`。不要修改 `onlineworker.spec`，它专用于 arm64。

## 验证构建产物

```bash
# 检查 DMG 文件
ls -lh mac-app/src-tauri/target/release/bundle/dmg/*.dmg
ls -lh mac-app/src-tauri/target/x86_64-apple-darwin/release/bundle/dmg/*.dmg

# 检查 sidecar binary 架构
file mac-app/src-tauri/binaries/onlineworker-bot-*
file mac-app/src-tauri/binaries/ccusage-*
```

预期输出：
```
onlineworker-bot-aarch64-apple-darwin: Mach-O 64-bit executable arm64
onlineworker-bot-x86_64-apple-darwin: Mach-O 64-bit executable x86_64
ccusage-aarch64-apple-darwin: Mach-O 64-bit executable arm64
ccusage-x86_64-apple-darwin: Mach-O 64-bit executable x86_64
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
pyinstaller onlineworker.spec --clean --noconfirm
```
