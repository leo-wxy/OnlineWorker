# OnlineWorker Mac App 打包指南

## 快速打包命令

### aarch64 (Apple Silicon) DMG

```bash
export NVM_DIR="$HOME/.nvm" && source "$NVM_DIR/nvm.sh" && nvm use 20 && cd /path/to/OnlineWorker && bash scripts/build.sh
```

产物目录：`mac-app/src-tauri/target/release/bundle/dmg/`。文件名中的版本号来自 `VERSION`，构建脚本会同步至应用配置，当前为 `1.11.2`。

在线更新当前暂时屏蔽，`createUpdaterArtifacts=false`。本地与 CI 保留 App 和 DMG 构建，不要求 updater 签名私钥；已有 updater 公钥保持原样。

> 说明：这条命令对应当前仓库的基础构建路径。额外 provider 扩展包不会自动被打进这个 DMG；如果你需要把扩展包一起打包，请在调用 `scripts/build.sh` 前设置 `ONLINEWORKER_PLUGIN_SOURCE_DIRS`。

### GitHub Tag 自动打包

仓库内置了 GitHub Actions workflow：`.github/workflows/release-dmg.yml`。

- 触发方式：
  - 推送版本 tag（例如 `1.10.0`）后自动执行
  - 手动 `workflow_dispatch`，并传入一个已存在的 `release_tag`
- 运行环境：
  - Apple Silicon：`macos-15`
  - Intel：`macos-15-intel`
- 构建入口：
  - 直接复用仓库根目录的 `bash scripts/build.sh`
- 产物处理：
  - 从指定 tag 检出源码，构建前校验 tag、`VERSION`、应用配置和 `Cargo.lock` 的版本一致
  - 两种架构分别构建、验证 App 版本与主程序/sidecar 架构，再上传 Actions artifact
  - 两种架构均成功后，统一创建或更新对应 GitHub Release，只上传两个 DMG；暂不生成或发布 updater 更新包、签名及 `latest.json`

CI 已配置 **Apple Silicon / aarch64** 和 **Intel / x86_64** 两条原生构建链。实际产物是否可运行仍须在对应架构的安装版验证，源码检查不能代替安装态验收。

### Updater 更新包签名

当前 DMG 发布不使用 updater 密钥。恢复在线更新包发布时，CI 必须设置 `TAURI_SIGNING_PRIVATE_KEY`，加密密钥还需设置 `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`。它们是 GitHub Actions Secrets，独立于下方 Apple 代码签名、公证凭据。私钥必须与 `mac-app/src-tauri/tauri.conf.json` 中 `plugins.updater.pubkey` 配对；生成 manifest 时会核对 key id，App 下载后再验证完整签名。

维护现有发行版时使用原有配对密钥，不要重新生成并替换公钥；旧版 App 无法验证另一套密钥签出的更新。独立发行版初次建立自己的更新渠道时，可在本地运行 Tauri signer 并将对应公钥配置到自己的 App：

```bash
mkdir -p .onlineworker-local/updater
mac-app/node_modules/.bin/tauri signer generate --write-keys .onlineworker-local/updater/onlineworker.key
```

通过 GitHub Secrets 设置页保存生成的私钥文件内容及密码，不在终端输出或提交私钥。受忽略的本地密钥目录不会进入仓库或安装包；原始密钥应由维护者安全备份。恢复签名更新包构建时可使用该路径，或通过 `TAURI_SIGNING_PRIVATE_KEY` 指定私钥文件/内容；更新包必须签名后才能发布。

### 正式签名与公证

在仓库的 GitHub Actions Secrets 中配置以下值；证书、密码和账号信息不要写进源码、文档示例或日志：

- `APPLE_CERTIFICATE`：Developer ID Application `.p12` 证书的 base64 内容
- `APPLE_CERTIFICATE_PASSWORD`：证书导出密码
- `APPLE_SIGNING_IDENTITY`：该证书的完整签名身份，后续发布保持一致
- `KEYCHAIN_PASSWORD`：CI 临时钥匙串密码
- `APPLE_ID`、`APPLE_PASSWORD`（App 专用密码）、`APPLE_TEAM_ID`：Apple 公证凭据

完整配置后，PyInstaller 使用同一身份签署内嵌 Python 二进制，Tauri 签署并公证 App；CI 校验代码签名、Team ID、公证票据和 Gatekeeper 结果后才上传。正式签名构建失败时禁止使用未公证的 DMG fallback。配置部分凭据会直接失败；全部未配置时仅使用 ad-hoc 签名产出开发版，不能宣称已正式签名或公证。

配置依据：[Tauri macOS 签名与公证](https://v2.tauri.app/distribute/sign/macos/)、[PyInstaller 内嵌二进制签名](https://pyinstaller.org/en/stable/feature-notes.html#macos-binary-code-signing)。当前仓库代码接通这些步骤，不代表凭据已配置或真实签名、公证已验收。

### 应用内更新

在线更新当前暂时屏蔽。“设置 → 维护 → 应用更新”保留当前版本及“打开官方下载页”，检查、下载与安装更新按钮禁用，用户通过 DMG 手动安装新版本。现有更新实现和签名校验保留，恢复时还需启用更新包生成、签名及 manifest 发布流程。

安装前要求任务已结束、没有未确认的发送，以及已关闭通过 OnlineWorker proxy 连接的远程 CLI。远程连接按生命周期保护安装，即使 CLI 暂时空闲也需先关闭；其真实 turn 状态仍由消息总线管理。独立 CLI 和直接连接 provider 的外部客户端不由该准入锁控制。

App 在确认空闲后创建旧包备份，复制完成后重新确认并续期准入，再停止 bot、安装、验证包版本与标识并重启。备份位于安装目录下的 `.OnlineWorker-update-*/previous.app`，同目录 `manifest.json` 记录原路径；安装失败尝试恢复旧包并重新启动先前运行的 bot。备份保留供人工恢复，不自动清理。重启后的自动健康回滚尚未实现。

当前源码检查与快速打包覆盖安装已完成过；线上 Release 的完整 updater 路径、实际签名拒绝、安装失败恢复、更新后服务恢复和 Intel 安装态仍待功能验收。配置 CI 不代表这些验收已经通过。

### x86_64 (Intel) DMG

在 Intel Mac 使用对应架构的 Python；Apple Silicon 可使用 Rosetta 和 x86_64 Python。共享构建入口会重建两个 sidecar，并为 Tauri 传入同一 target：

```bash
cd /path/to/OnlineWorker
ONLINEWORKER_TARGET_TRIPLE=x86_64-apple-darwin \
  PYTHON_EXECUTABLE=/usr/local/bin/python3.13 bash scripts/build.sh
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

`scripts/build.sh` 会同步应用配置与 Cargo 锁文件的版本，然后自动检测当前机器架构并执行四个构建阶段。可用 `ONLINEWORKER_TARGET_TRIPLE` 指定架构，`PYTHON_EXECUTABLE` 指定相应 Python；显式 target 的产物位于 `target/<target>/release/bundle/`，默认本机构建仍位于 `target/release/bundle/`：

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
