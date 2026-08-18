# Phase 23 Research: Plugin-Owned Codex Account and Session Asset Management

> 2026-08-18 implementation follow-up: this document preserves the original planning research. The shipped transport subsequently moved from one process per action to one independent resident account-feature JSONL worker; it still imports before live runtime, remains provider-neutral, and does not use owner bridge or app-server authority.

## Summary

本次研究只覆盖规划事实和实现约束；没有修改产品代码、ROADMAP、STATE、CONTEXT 或 UI-SPEC。Cockpit Tools 行为基线已核对：`/tmp/cockpit-tools-root-3596316` 的 `HEAD` 是 `35963163813d7424b63cd6053874ce5fc7973d03`，工作树干净；没有复制其 CC BY-NC-SA 源码。

结论：Phase 23 应新增一个很薄的、provider-neutral 的 account-feature discovery/mount/action seam；Codex 的页面、RPC action、模型、存储、兼容解析、会话文件操作全部留在 `plugins/providers/builtin/codex/`。当前 host 不能直接运行外部插件 TS 页面：Vite 只编译 `mac-app` 源码，打包脚本只把 provider 资源复制到 Tauri `provider-plugins/`。因此最小可落地方案是“manifest 声明 + 构建期 plugin frontend entry glob/registry + 中性 host selector/page mount + 独立 one-shot plugin action transport”，不引入 iframe/WebView、provider-id 分支或未来插件框架。

最重要的风险是加密依赖和边界：当前 `mac-app/src-tauri/Cargo.toml:26-38` 没有 AES/ZIP/SQLite 加密依赖，`requirements.txt:1-9` 也没有 `cryptography`。AES-256-GCM 是锁定要求，计划阶段必须选择一个最小、审计过的实现（优先单一 Rust `aes-gcm` 依赖，或在 Codex plugin runtime 中使用已批准的等价库）；不能把“用 stdlib”写成未验证承诺，也不能用 Cockpit 源码。其余 ZIP、JSON、hash、临时文件、路径检查可复用 Rust/Python 现有标准库和现有原子写模式。

所有 D-01..D-40 已视为锁定，不在本研究中重新取舍。页面必须在 bot/provider runtime/owner bridge/Codex app-server 停止时仍可用；Apply 只投影有效 `$CODEX_HOME`/`~/.codex` 的 credential file，不重启、检查、通知或连接任何进程。

## Package Legitimacy Audit

| Package | Status | Evidence | Fit and decision |
|---------|--------|----------|------------------|
| `cryptography==48.0.1` | **[VERIFIED]** | [PyPI 48.0.1](https://pypi.org/project/cryptography/48.0.1/) 由 Python Cryptographic Authority 发布，使用 Trusted Publishing 和可验证 provenance；[project metadata](https://pypi.org/project/cryptography/) 标记 Production/Stable、Python `>=3.9`、`Apache-2.0 OR BSD-3-Clause`；[official AESGCM API](https://cryptography.io/en/stable/hazmat/primitives/aead/) 直接支持 256-bit key、12-byte nonce 和 `InvalidTag` tamper failure；[GHSA-537c-gmf6-5ccf](https://github.com/pyca/cryptography/security/advisories/GHSA-537c-gmf6-5ccf) 明确说明 wheel 漏洞在 `48.0.1` 修复。 | 选为 Codex Python plugin 的单一 AES-256-GCM 生产原语依赖。`48.0.1` 为 CPython 3.9+/3.11+ 提供 macOS universal2 wheel，覆盖仓库 DMG 脚本支持的 arm64/x86_64；[49.0.0 changelog](https://cryptography.io/en/stable/changelog/) 明确移除 macOS x86_64 wheel，因此 Phase 23 不升到 49/50。 |

Audit disposition:

- 包名、owner、source repository、license、release provenance、Python 版本和 AESGCM API 均从官方 PyPI/PyCA 资料核验，不是 typosquat/新生包，无 `[ASSUMED]`/`[SUS]`/`[SLOP]` 结论。
- 实现必须使用 `cryptography.hazmat.primitives.ciphers.aead.AESGCM`，32-byte random key，12-byte random nonce，不自行实现 AES/GCM/tag。
- `requirements.txt` 是依赖/根配置变更；虽然包合法性已验证，执行计划仍必须在修改前通过用户确认 checkpoint。未确认前不安装、不修改 requirements、不运行 package/build 验证。
- 引入后必须在 synthetic fixture 中验证 AESGCM round-trip/tamper/vector，并在获得另行打包许可后验证 PyInstaller 收集该 wheel。

## Current Architecture Facts

### Provider discovery and the smallest neutral seam

- `core/providers/contracts.py:68-80` 的 `ProviderManifestCapabilities` 只有 `sessions`, `send`, `approvals`, `questions`, `photos`, `files`, `usage`, `commands`, `launch_methods` 等字段；没有 account/page capability。
- `core/providers/contracts.py:93-106` 的 `ProviderMetadata` 和 `:173-189` 的 `ProviderDescriptor` 只表达 provider runtime/session/message/lifecycle hooks，没有账户资产或页面挂载描述。
- `core/providers/manifest.py:85-100` 将 manifest capability 转成 `ProviderManifestCapabilities`；`:112-173` 解析通用 provider metadata；`:176-181` 通过 `plugin.yaml` 读取 builtin manifest。新增 capability 应从同一 discovery 层进入，但不要把 Codex 字段塞进 provider runtime capability。
- `core/providers/registry.py:13-27` 固定 builtin/overlay roots；`:37-48` 加载 `module:function` descriptor；`:51-86` 校验 manifest id 与 descriptor name 并隔离加载失败；`:89-90` 暴露 load failures；`:183-184` 列出 provider。这个模式可借鉴“声明、加载、失败隔离”，但 account feature 不应依赖 `_PROVIDERS` 的 live runtime descriptor。
- `plugins/providers/DEVELOPMENT.md:22-48` 规定 manifest 是插件入口、overlay import root 和路径安全边界；`:90-121` 规定 descriptor/entrypoint 形状；`:235-250` 规定 build 注入会复制目录到 `mac-app/src-tauri/provider-plugins/` 并要求按 builtin/overlay 规则验证；`:269-272` 明确 shared Rust command 不应写死 provider ID。Phase 23 的 generic feature seam 应遵守同一 ownership/validation 规则。
- `plugins/providers/builtin/codex/plugin.yaml:1-12` 是 Codex manifest identity；`:33-58` 声明当前 runtime capabilities；`:140-142` 声明 Python descriptor/config/completion entrypoints。当前 manifest 没有 account feature。
- `plugins/providers/builtin/codex/python/provider.py:61-128` 的 `create_provider_descriptor()` 构造 provider runtime descriptor；会话 hooks 从 `:28-59` 进入。账户/会话资产应新增同目录下独立 feature descriptor/handler，不挂到这些 live session hooks 上。

### Owner bridge and Tauri IPC are the wrong runtime dependency

- `mac-app/src-tauri/src/commands/provider_bridge_common.rs:13-83` 的 `provider_bridge_env()` 和 `provider_owner_bridge_socket_path()` 服务于 Provider owner bridge；`:107-173` 还包含 bridge sidecar/process-tree 处理。D-02/D-12 明确不允许账户页复用这个 live runtime seam。
- `mac-app/src-tauri/src/commands/provider_sessions.rs:144-217` 通过 Unix socket 请求 owner bridge，`:347-398` 以同一方式列会话，`:408-486` 归档；这些路径都要求 runtime bridge ready，不适合作为离线账户页。
- `main.py:99-205` 当前一次性 bridge 只支持 `usage-source`, `usage-catalog`, `list`, `read`, `send`, `archive`。若复用 sidecar 进程，新增应是独立的中性 `plugin-action`/feature RPC，而不是扩展 provider-session bridge；每个请求自包含、无持久 bridge、无事件发布。
- `mac-app/src-tauri/src/lib.rs:430-476` 注册现有 Tauri commands；`mac-app/src-tauri/src/commands/mod.rs:1-17` 导出 command modules。新增 host commands 应只处理中性 discovery/mount/action/save/open/file capability，Codex action 名称和 payload 由插件 opaque 转发。

### Current host UI is static and Vite has no runtime plugin frontend loader

- `mac-app/src/App.tsx:27-68` 静态 lazy import 页面；`:70-85` 只维护固定 `activeTab`；`:217-230` `getTabIcon` 用固定 tab switch；`:299-337` sidebar 从 `PRIMARY_APP_TABS` 映射；`:440-545` 固定 active-page mount。这里正是增加一个通用动态“账号”入口、selector、loading/error boundary 的位置，但不得写 `if providerId === "codex"`。
- `mac-app/src/utils/appTabs.js:1-7` 只有固定 `PRIMARY_APP_TABS`/`ALL_APP_TABS`；`mac-app/src/i18n/types.ts:40-67` 和 `mac-app/src/i18n/locales/zh.ts:52-68` 也是 host 固定文案。host 可以拥有 generic `账号`入口文案（UI-SPEC 已锁定），Codex 账号/会话业务文案必须来自插件。
- `mac-app/vite.config.ts:1-16` 只启用 React plugin，`mac-app/package.json:6-33` 没有 plugin loader/webview 依赖；不应新增。Vite 的 build-time `import.meta.glob` 可作为当前 builtin plugin entry 的最小编译 seam，避免运行时 TS/iframe。
- `scripts/build.sh:12-45` 将外部 plugin source 复制到 `mac-app/src-tauri/provider-plugins`，`:207-225` 在 Tauri build 前执行 staging；`mac-app/src-tauri/tauri.conf.json:35-39` 只将 `provider-plugins` 作为 bundled resource。`mac-app/src-tauri/src/lib.rs:248-273` 将 bundled resource dir 设置为 `ONLINEWORKER_PROVIDER_OVERLAY`。这条路径只支持运行时 Python/YAML/icon 资源，不会让 Vite 运行时编译任意 TS/React。
- `mac-app/src-tauri/src/commands/config_provider/provider_assets.rs:1-69` 目前仅 `include_str!` builtin manifest/icon；`:42-51` 的 fallback 资产没有 page bundle。不能把 Codex 页面代码放进 Rust host；应在构建阶段把 plugin frontend 作为 Vite 输入，或先限定 account-capable frontend 为仓内 builtin，并保留 manifest/entry 的未来扩展点。

### Existing Codex local file facts and hardcoded-path risks

- `plugins/providers/builtin/codex/python/transport.py:25-27` 的 `default_codex_home()` 是当前正确 precedence：`CODEX_HOME`（非空）否则 `~/.codex`。新 feature 应复用为纯 helper，并将 `home` 显式传给所有扫描/写入函数。
- `plugins/providers/builtin/codex/python/storage_runtime.py:11-12` 当前把 `CODEX_SESSIONS_DIR` 写死为 `~/.codex/sessions`；`:35-55` 也把 `~/.codex/session_index.jsonl` 写死；Phase 23 必须修成 effective-home 参数，不能继续让测试读真实 home。
- `storage_runtime.py:87-97` 递归收集 `.jsonl`；`:129-225` 解析 session_meta、用户可见 source、id/cwd/timestamps 和 response event；`:228-268` 从 `state_5.sqlite` 的 `threads` 读取 `archived=0`；`:271-312` 合并 rollout/index/cache。可复用纯 parser，但不能依赖 OnlineWorker Session projection。
- `plugins/usage/builtin/ccusage/python/runtime.py:38-69` 从 `CODEX_HOME`/`~/.codex` 读取 sessions/archived_sessions；`:93-142` 调用 ccusage sidecar，并返回 daily token/cost。D-31 禁止把 account page 接到该 Usage plugin；Phase 23 应在 Codex plugin 内按本地文件独立计算近 30 天数据。

### Existing write/security patterns

- `core/storage.py:122-151` 采用临时文件后 `os.replace` 的原子 JSON 写入；可复用思路，但 account detail 必须先加密且 key/detail/index 都要单独控制权限。
- `mac-app/src-tauri/src/commands/terminal.rs:126-173` 是通用系统打开命令的现有模式；`support_bundle.rs:866-980` 展示 native save dialog、cancel 返回和 reveal 文件模式。新 account/session host capability 可复用 native file dialog/open browser，但不得把 Codex 字段放进通用 command。
- `mac-app/src-tauri/Cargo.toml:26-38` 目前只有 Tauri、serde/serde_json/yaml、tokio、chrono、ureq、uuid、base64 等；没有 `aes-gcm`, `zip`, `sha2`, `rusqlite`。`requirements.txt:1-9` 没有密码学库。AES-GCM 不是 stdlib 能力，计划必须显式解决依赖/实现审计问题。

## Recommended Minimal Architecture

### 1. One generic feature descriptor, separate from Provider runtime

在 manifest 中增加一个中性 account-feature declaration（例如 `features.account`），最小字段只包括：feature id/type、enabled、plugin display label/icon reference、backend action entrypoint、frontend entrypoint/schema version。`enabled` 是 feature declaration 自身的静态开关，不读取 Provider runtime config。不要向 `ProviderManifestCapabilities` 增加 Codex account 字段，也不要把 account feature 当作 `sessions`/`usage` capability。

Python 侧新增独立的 generic feature loader：`core/account_features.py` 直接遍历仓内 builtin manifest，并只复用 `core/providers/manifest.py` 的无副作用 YAML helper；不得 import `core.providers.registry` 或 `_PROVIDERS`。它只返回 enabled、entry 文件真实存在且路径受限的中性 descriptor。Phase 23 不编译 overlay frontend；overlay manifest 声明 account frontend 时返回 isolated `unsupported_frontend_source` diagnostic，不进入 selector。Codex handler 放在 `plugins/providers/builtin/codex/python/account_feature.py`，内部再调用 plugin-owned modules。

### 2. Generic host shell and isolated action transport

host 做四件事：发现 account-capable features；若至少一个则显示一个 `账号` sidebar entry；展示 selector；为每个 feature 建立 loading/error/retry/diagnostic boundary。所有业务请求通过一个 generic `invoke_account_feature(feature_id, action, payload)`（或等价 one-shot action）opaque 转发；host 不解析 Codex action、credential、session、OAuth 或 error vocabulary。

这个 action transport 不应走 `provider_owner_bridge.sock`、Task Board、EventBus、notification 或 live app-server。现有 bundled Python sidecar 可扩展独立 operation，但 `main.py` 必须在任何 Telegram/bot/lifecycle/state import 之前，用 stdlib-only argv bootstrap 识别 feature list/action 并直接退出；普通运行才继续现有 imports。测试用 subprocess/import marker 证明 one-shot 没有加载 `core.state`, `core.lifecycle`, `core.providers.registry`, bot/Telegram。Tauri 只负责 one-shot、超时、JSON 边界和通用错误。

### 3. Frontend packaging: build-time plugin entry, not runtime WebView

当前最小可实现方案是让 builtin feature 暴露 `plugins/providers/builtin/*/frontend/account-entry.tsx`，host 用一个 build-time `import.meta.glob` 收集 entry，entry 返回中性 `{ metadata, Component }` contract。Codex 的所有 JSX、labels、models、forms、action names、errors 放在 `plugins/providers/builtin/codex/frontend/`；host 只根据 discovery metadata 选择 Component。这样没有 provider-id branch，也没有新增依赖或 iframe/WebView。

现有 overlay 只在 package 阶段复制 runtime resource，不能直接进入 Vite bundle；规划中应明确 Phase 23 的 Codex 是仓内 builtin，future overlay frontend 要求“构建期 source staging/manifest validation”再扩展，不要现在设计运行时 JS loader。不要把 page bundle 放进 `provider_assets.rs` 的 Codex-specific Rust `include_str!` 分支，也不要把 page HTML 放 Tauri resource 后用嵌入 WebView。

### 4. Codex-owned storage and pure local operations

建议目录（名称可在 plan 固定）位于 OnlineWorker app data 下的 Codex plugin-owned root，例如：

```text
<OnlineWorker data>/plugins/providers/codex/accounts/
  key
  index.json                 # plaintext non-secret summary only
  accounts/<stable-id>.json  # encrypted envelope
  backups/                    # bounded recovery files
  session-trash/<timestamp>/  # manifest-backed reversible trash
```

不能使用 Cockpit 的 `~/.antigravity_cockpit`，也不能把 Cockpit 文件当 live datastore（D-25）。Account store、session asset manager、compat parser、OAuth state、ZIP handling 都由 Codex plugin package 所有。host 的 app data path 只作为 generic writable root capability 传入。

### 5. Crypto and atomicity decision required by plan

账户 detail：随机 32-byte key，AES-256-GCM，随机 12-byte nonce，envelope 至少包含 `version`, `kind`, `algorithm`, `key_id`, `nonce`, `ciphertext`, `encrypted_at`。key 文件 user-only（Unix `0600`）；index/detail/key/apply credential file 都采用 same-directory temp + fsync/replace（平台允许时）并在替换前保存 bounded backup。读到支持的 legacy plaintext record 后，成功解析才重写加密；失败不覆盖原文。

当前仓库没有可直接复用的 AES-GCM。推荐计划只引入一个最小、锁版本的 AES-GCM crate（或已批准的 equivalent runtime library），不自己实现密码学、不调用未经验证的 openssl CLI、不复制 Cockpit `secure_account_storage.rs`。如果采用 Rust crate，必须把它放在“generic secure primitive”或专门的插件 backend boundary，Rust host 代码仍不能包含 Codex account model/labels；如果采用 Python library，必须说明 PyInstaller hidden import、requirements/lock 和 fallback。该点在计划阶段不能含糊带过。

### 6. Apply transaction

`default_codex_home()` 解析有效 home；只读 `<home>/auth.json`，生成目标 JSON，写 `<home>/auth.json.tmp-*`，权限继承/收紧为 user-only，验证序列化后再 atomic replace。旧文件存在时先保留 backup；只有 credential replace 成功且可重新读取/结构校验后，才更新 plugin index 的 `current`/applied marker。任一步失败，按逆序恢复原 credential、恢复 index/current；错误响应只含原因和是否回滚，不含 secret。整个流程禁止 process scan、runtime readiness、restart/reconnect、EventBus/notification。

## Data/Action Contracts

下面是供计划拆分的最小 contract；字段名可调整，但语义不能弱化。

### Generic host contract

```text
AccountFeatureDescriptor (host-visible, non-secret)
  featureId, label, icon, frontendEntry, protocolVersion

AccountFeatureActionRequest
  featureId, action (opaque string), payload (opaque JSON)

AccountFeatureActionResponse
  ok, data (opaque JSON), error { code, message, retryable, diagnosticId? }

NativePathHandle
  handleId, featureId, mode (open|save), displayName, expiresAt

LoopbackCallbackSpec (generic native capability)
  preferredPort?, callbackPath, timeoutMs

LoopbackCallbackHandle
  handleId, redirectUri, listening
```

Host list response只返回 feature metadata 和 load error；不会返回 account detail、token、API key、OAuth verifier、session content。`featureId` 是 descriptor key，不应被 host 当作 Codex provider-id 做分支。Native open/save dialog 返回一次性、短时、绑定 feature/mode 的 opaque handle；React 不获得真实路径。调用 action 时 handle 走独立 trusted capability context，由 Tauri 解析后传给 backend entry，不能放在普通 payload。cancel 不产生 handle且不写文件；handle 跨 feature、过期、重放、模式不符均拒绝。

OAuth 不能让一次性 plugin action 自己在返回 auth URL 后继续持有 listener。最小可执行链是：Tauri generic capability 仅在 `127.0.0.1` 绑定受限端口/路径并返回 handle/redirect URI；Codex plugin 用该 URI 生成授权 URL；host 打开系统浏览器并对 handle 做 bounded await/cancel；捕获的完整 callback URL 只在 plugin-owned UI 内存中瞬时转交给 opaque complete action，host 不解析 code/state。若首选端口不可绑定，保留同一 redirect URI 并进入手工 callback fallback。listener 必须限制 request-target 大小、只接受精确 path、单次完成、超时清理，不写 callback query 到日志。

### Account internal model

区分 plaintext index 和 encrypted detail：

```text
IndexRecord: id, stable_identity_display, identity_key_hash, auth_mode,
  source, is_current, external_state, created_at, updated_at

EncryptedAccountDetail: schema_version, stable_identity fields, auth_mode,
  credentials, import_source, imported_at, updated_at, extra: JSON object
```

`credentials` 只能在 explicit import/export/apply action 的 backend boundary 出现；普通 list/account-card response 使用 IndexRecord 的 redacted DTO。`extra` 保存所有已支持输入对象中的 unknown fields；parse -> internal -> export 必须合并回原 JSON 对象，不能只把未知字段放进会丢失的 typed struct。

Identity upsert 建议按稳定身份和认证模式定义 deterministic key：优先使用可解析的 Codex account identity（agent identity 的 account/chatgpt user/agent runtime 组合、token 的 account id 或 email、API key 的不可逆 hash）；缺少可验证 identity 就拒绝，不以随机 token 或明文 secret 作为 UI identity。re-import 命中同一 key 时更新原 record、保留兼容 unknown fields；identity 不确定时报告 per-item ambiguous/rejected，不创建 duplicate。刷新时 hash 当前 effective `auth.json` 的可识别 identity；命中则标记 external matched，未命中则 external unmanaged，不自动 import/apply。

### Cockpit account import/export shape

- 接受 top-level object 或 array；Cockpit `parseCockpitToolsCodexExport` 对 object 包装为一个 record，对 array 逐条处理，其他 shape 返回 empty（`cockpit-tools@3596316:src/utils/codexExportFormats.ts:525-534`）。OnlineWorker 不能把 unsupported shape 当成功空导入，应在 UI 返回 version/shape error。
- Token storage 必需 `id_token`, `access_token`, `refresh_token`, `account_id`, `last_refresh`, `email`, `type: "codex"`, `expired`；可选 `account_note`, `two_factor_secret`, `account_password`, `phone_number`, `mail_url`（`cockpit-tools@3596316:src/utils/codexExportFormats.ts:31-45`）。
- Agent identity storage 必需 `auth_mode: "agentIdentity"`, `agent_identity`, `account_id`, `user_id`, `email`, `type: "codex"`（`:47-54`）；builder 使用 `agent_runtime_id`, `agent_private_key`, `account_id`, `chatgpt_user_id`（`:264-296`）。
- API key storage 使用 `auth_mode: "apikey"`, `OPENAI_API_KEY`, `email`，可选 `api_base_url`, `api_provider_id`, `api_provider_name`（`:485-509`）。
- `transformCodexExportJson` 的 `cockpit_tools` 输出是 JSON array，即使只有一条 account；pretty JSON 两空格（`:512-523`, `:552-585`）。`agentIdentity` 不应伪造 `access_token`；regular token 保留 access/refresh；API key 输出 API-key shape。Cockpit tests 的精确断言见 `cockpit-tools@3596316:src/utils/codexExportFormats.test.ts:43-61`, `:84-104`, `:188-214`。
- Cockpit Rust `CodexAccount` 很宽（`cockpit-tools@3596316:src-tauri/src/models/codex.rs:97-229`），Phase 23 只实现 D-08 范围；未使用字段仍原样进 `extra`，以满足 D-19，而不是照搬模型。

### OAuth contract

UI 先请求 generic loopback handle（Codex 当前行为使用 preferred port `1455` 和 `/auth/callback`），再把 host 返回的 redirect URI 传给 `start_oauth`。Codex plugin 固定 `CLIENT_ID=app_EMoamEEZ73f0CkXaXp7hrann`、authorize endpoint `https://auth.openai.com/oauth/authorize`、token endpoint `https://auth.openai.com/oauth/token`；payload/config 不可覆盖 endpoint/client/issuer，redirect 只接受 localhost/1455/exact path。backend 生成 random verifier/state 和 PKCE URL。Cockpit 行为证据：`cockpit-tools@3596316:src-tauri/src/modules/codex_oauth.rs:14-23`, `:376-455`, `:656-689`。

自动 callback 由 generic host broker 捕获完整 URL 后瞬时交还 Codex plugin，手工 callback 直接交给同一 complete action；两者都使用同一个 pending state 做 exact comparison，只接受精确 redirect host/port/path 与非空 code/state。`oauth_server.rs:71-98` 是该校验形状，`:100-135` 支持完整 URL/path/query fragment manual input，`:137-235` 展示 request-target/path 限制。complete action 随后执行 bounded authorization-code exchange、验证 credential/identity、写入 account library，且不 auto-apply。state/verifier 只在 plugin-owned temporary state dir，成功/过期/取消清除；host/UI/plugin 日志均不得记录 URL query、code、verifier/token。必须通过 system browser；不得嵌入 login WebView。

### Session asset contract

- effective home 下读取 `sessions/`, `archived_sessions/`, `session_index.jsonl`；列表字段至少 session id/title/cwd/updatedAt/location/state，标题搜索只匹配 title。当前 Codex runtime 的用户可见过滤和 index/rollout merge 见 `storage_runtime.py:15-55`, `:129-225`, `:271-312`。
- 近 30 天使用 local rollout token events；Cockpit `codex_session_usage.rs:1-8` 说明算法：优先 `last_token_usage`，按完整快照签名去重，缺 last 时使用 `total_token_usage` 高水位差，fork 时跳过父 rollout 重放前缀；`:25-100` 定义 totals/report；`:231-238` query/sync；`:1434-1439` 按 model 估算成本。成本不可得返回 unavailable，不伪造 0。
- ZIP export manifest exact fields: `kind`, `package_version`, `exported_at`, `sessions[]`; item 含 `session_id`, `title`, `cwd`, `updated_at`, `relative_rollout_path`, `file_entry`, `size_bytes`, `sha256`, `session_index_entry`, `source_instance`（`cockpit-tools@3596316:src-tauri/src/modules/codex_session_manager.rs:258-280`）。export writes `manifest.json` and `files/{:04}-{sanitized_id}/rollout.jsonl`, Deflate/0644 (`:1048-1211`, `:1680-1747`)。
- import 先读 manifest、target home、existing IDs；same ID + same hash 可 skip，different content 是 conflict，不能 overwrite；在写完临时文件并重新计算 size/SHA 后 rename，index update 失败恢复 index/written files（`:1214-1426`, `:1353-1365`, `:1848-1913`）。
- ZIP path validation 拒绝 absolute/`.`/`..`/colon；manifest item 需 file path under `files/`, `.jsonl`, 64-hex SHA（`:1648-1677`）。`relative_rollout_path` 只允许 `sessions`/`archived_sessions` 第一段及 `rollout-*.jsonl`（`:1794-1823`）。
- trash 是 app/plugin data 下 manifest-backed reversible move；Cockpit `get_session_trash_base_dir()` 使用 app data + `cockpit-tools-codex-session-trash`，legacy `~/.Trash` 仅 optional read（`:2148-2177`）；manifest 保存 session identity/index/original path，move 用 rename（`:2183-2248`）。Phase 23 可在自己的 plugin data 使用同一语义，但不提供 permanent delete/copy-to-instance/cross-instance。
- restore 先验证 trash file 存在且 rollout session id 与 manifest 一致，目标冲突时不覆盖；成功后恢复 mtime/index，失败恢复 index，只有成功才清理 trash (`:2633-2750`)。当前 Cockpit 默认 visibility repair 是 `official_state_db_only(Quick)`：target provider 读取 effective home 的 `config.toml.model_provider`，缺失时为 `openai`；只检查 `<home>/state_5.sqlite` 与 `<home>/sqlite/state_5.sqlite` 的既有 `threads` 表，只更新既有行的 `model_provider`，并修复这些行 `rollout_path` 引用文件首条 `session_meta`。它不修 `session_index.jsonl`、不扫描 `sqlite/codex-dev.db`、不改 timestamp、不建表/改 schema、不重建 metadata。Phase 23 逐项复刻这个 current quick 语义，并用 SQLite transaction/backup 与 rollout backup→atomic replace→rollback；不得 inspect process 或跨 instance（`codex_session_visibility.rs:273-302`, `:1400-1425`, `:3529-3560`）。

### Apply and file permission contract

当前 Cockpit effective home precedent 是 `get_codex_home()` 使用 env 或 `~/.codex`（`cockpit-tools@3596316:src-tauri/src/modules/codex_account.rs:1854-1860`），auth path 是 `home/auth.json`（`:1878-1881`）。其 `write_auth_file_to_dir` 负责 auth projection/atomic write（`:6687-6708`）；Phase 23 只借鉴文件形状和边界，不复制代码，并且必须补齐失败 rollback、secret-safe logging、no-runtime-side-effect 约束。

## Cockpit Compatibility Findings

1. **Account package is array-compatible, not a UI convention.** Cockpit’s `cockpit_tools` transform always emits an array and accepts object-or-array input. A single-object-only implementation would break bidirectional compatibility.
2. **Three credential modes have materially different required fields.** Token, `agentIdentity`, and API-key records cannot be normalized by filling fake token fields. In particular agent identity output omits `access_token`; API key uses `OPENAI_API_KEY` and `auth_mode: "apikey"`.
3. **Unknown fields require raw-object retention.** Cockpit’s broad `CodexAccount` and alias/compat import paths (`cockpit-tools@3596316:src-tauri/src/modules/codex_account.rs:4735-4917`) normalize known fields but do not itself guarantee every unknown field survives. Phase 23 must store original parsed object/`extra` and merge known updates back on export. Tests must include nested unknown fields, unknown top-level fields, and a supported import->export equality comparison modulo documented normalization.
4. **Local import is structural, not network validation.** Cockpit’s `import_from_local` reads effective `auth.json` and recognizes agent/API/PAT/token forms (`cockpit-tools@3596316:src-tauri/src/modules/codex_account.rs:7813-7891`). Phase 23 D-20 requires no refresh/login/network call during import.
5. **Encrypted details and plaintext index are distinct.** Cockpit secure storage documents plaintext summary/index, encrypted detail, legacy plaintext rewrite (`cockpit-tools@3596316:src-tauri/src/modules/secure_account_storage.rs:1-5`). Key is random 32 bytes, atomic, chmod 0600 (`:30-61`); AES-GCM envelope is versioned with 12-byte nonce (`:15-28`, `:68-120`). Tests use temp-dir overrides and verify ciphertext does not contain secret (`:136-175`).
6. **Session transfer has integrity and conflict semantics that must be tested, not inferred.** Manifest kind is `codex-session-export`, version 1, with per-file SHA-256; path traversal and hash mismatch reject before write; same-id same-hash skip and same-id different-hash conflict; index rollback is part of failure behavior.
7. **Trash is reversible but not “delete with undo UI”.** It moves rollout files into timestamped app-data trash and stores original path/index in manifest. Restore verifies identity and index consistency before cleanup. Permanent delete functions exist in Cockpit (`delete_trashed_sessions`) but are explicitly out of scope.
8. **Visibility repair is a mutation with backup/rollback.** Cockpit 还保留旧/深度实现，但当前默认路径只修 official state DB 与其引用的 rollout，不修 session index。Phase 23 只实现这个 current quick 路径，限定 effective local Codex home，不 inspect process、不协调 instances，并保留“backup -> mutate -> rollback on error”语义。

## Security/Threat Model Inputs

| Input / boundary | Threat | Required behavior |
|---|---|---|
| Token/API key/agent private key | accidental plaintext in list, logs, diagnostics, frontend state | encrypted detail; redacted list DTO; no secret in errors/logs; explicit export/apply only |
| OAuth code/state/verifier | CSRF, code interception, replay, query leakage | random PKCE/state; exact state match for auto/manual callback; expiry/cancel cleanup; system browser only |
| Imported JSON | malformed shape, unsupported mode, missing identity, unknown-field loss | per-item structural validation; preserve raw unknowns; reject unsupported version/shape clearly |
| Imported ZIP | path traversal, symlink/absolute path, zip bomb/oversize, malformed manifest | size/file-count bounds; reject absolute, `..`, colon, symlink and unexpected entries; validate kind/version/path/size/hash before writing |
| Existing session ID | silent overwrite/data loss | same hash skip; different hash conflict; no overwrite; per-item result |
| Effective `CODEX_HOME` | env points outside expected home or file changes during apply | resolve once; operate only `home/auth.json`; preserve old bytes/mode; atomic replace; backup and rollback |
| Plugin storage | key disclosure, world-readable files, partial writes/corruption | random key in plugin dir mode 0600; encrypted details; index/detail/key atomic; backup/repair on legacy migration |
| Path inputs/file dialog | arbitrary file read/write, symlink escape | one-shot feature-bound open/save handle via trusted context; reject payload paths, existing symlink, parent escape and replay; atomic 0600 destination |
| Logging/diagnostics | token fragments, OAuth URL, session content, cwd leakage | structured safe error codes/reasons; never log payload/credentials/session lines; diagnostic IDs only |
| Concurrent actions | torn index/detail/auth/session state | one cross-process lock file under plugin data root shared by account/OAuth/apply/ZIP/trash/restore/repair; temp same-dir writes; commit order and rollback |
| Visibility repair/trash restore | partial file/index mutation | manifest/backup first, mutate only selected effective home, restore prior index/files on failure, report unchanged/rolled-back |

Failure semantics are part of the API: canceling native save dialog is silent; import partial results are `ok/skipped/rejected`; unsupported format is a clear shape/version error; apply failure says rollback status and leaves current marker unchanged; session import/trash/restore failure says whether files/index were untouched or restored. Never return a stack trace containing paths, payloads, or secrets to frontend.

## Implementation File Map

This is a planning map, not a claim that files already exist.

| Area | Proposed location | Responsibility |
|---|---|---|
| manifest/feature declaration | `plugins/providers/builtin/codex/plugin.yaml`; generic parser near `core/providers/manifest.py`/new neutral feature module | declaration and validated non-secret metadata only |
| generic discovery | `core/account_features.py` + pure YAML helper in `core/providers/manifest.py` | builtin-only enabled discovery, isolated failures, no provider registry/live imports |
| generic Tauri host | `mac-app/src-tauri/src/commands/account_feature.rs` + `mod.rs`/`lib.rs` registration | opaque action, trusted data root/path handles, browser/loopback/file/save, generic errors/timeouts |
| generic host React | `mac-app/src/App.tsx` minimal dynamic sidebar/mount; new generic host component | one `账号` entry, selector, loading/error boundary; no Codex labels/models/actions |
| Vite entry contract | generic host import/glob; plugin-owned entry under `plugins/providers/builtin/codex/frontend/` | build-time component discovery; no iframe/WebView/runtime TS loader |
| Codex frontend | `plugins/providers/builtin/codex/frontend/` | account cards/modal, session assets hierarchy, all Codex labels/actions/errors/a11y |
| Codex action bridge | `plugins/providers/builtin/codex/python/account_feature.py` plus one-shot CLI dispatch | action routing independent of provider owner bridge/runtime |
| account model/import/upsert | `plugins/providers/builtin/codex/python/account_model.py`, `compat.py` | auth modes, identity key, unknown raw JSON, Cockpit shape/aliases/per-item validation |
| encrypted store | `plugins/providers/builtin/codex/python/account_store.py` (or backend with audited AES primitive) | key/index/detail envelope, permissions, atomic writes/backups/legacy migration |
| OAuth | generic Tauri loopback broker + `plugins/providers/builtin/codex/python/oauth.py` | host 仅绑定/捕获，Codex plugin 负责 PKCE/state/manual parser/token exchange/pending state/safe errors |
| apply | `plugins/providers/builtin/codex/python/apply.py` | effective home/auth.json transaction, backup/rollback, no process/runtime side effects |
| sessions | `plugins/providers/builtin/codex/python/session_assets.py` | effective-home list/title search/30-day local token-cost/trash/restore/visibility repair |
| ZIP | same Codex session module or focused `session_package.py` | manifest v1, ZIP bounds/path/hash/conflict/index rollback |
| tests | `plugins/providers/builtin/codex/tests/`, host Rust tests, frontend Node tests | tempdir-only credentials/home/ZIP/OAuth fixtures; neutral host isolation and UI states |

The exact final split should remain small. Do not create a general plugin SDK, account framework, provider-independent credential schema, or shared session abstraction for future Claude/Codemaker.

## Pitfalls

- Do not add `codex` branches to `App.tsx`, shared Rust commands, shared i18n models, `ProviderSettingsPanel`, `provider_sessions.rs`, `provider_usage.rs`, Task Board, EventBus, or notification code.
- Do not use `provider_owner_bridge.sock` merely because it already carries JSON; that socket is runtime/lifecycle-coupled and unavailable under D-02.
- Do not assume a staged `provider-plugins/` resource can supply React/TS at runtime. Current Vite build is compile-time and current Tauri bundle resource is Python/YAML/icon only.
- Do not hardcode `~/.codex`; `CODEX_HOME` precedence must be captured once and passed to every operation. Existing `storage_runtime.py:11-12` and `:39-40` are explicit risks.
- Do not treat `auth.json` read as proof of a managed account. Refresh must distinguish matched external credential from unmanaged external credential and require explicit import decision.
- Do not mark imported account current. Import updates library only; Apply is explicit and only then updates current marker.
- Do not serialize a typed subset and silently discard Cockpit unknown fields. Raw object/extra merge is mandatory.
- Do not expose API key/token fields in list DTO, React state persistence, logs, diagnostic bundle, or generic Tauri errors.
- Do not make a one-shot plugin process own a listener after it returns. Bind the generic loopback broker before building/opening the authorization URL; host must never parse OAuth code/state and callback URLs must not enter logs or frontend persistence.
- Do not import `core.providers.registry`, `core.state`, `core.lifecycle`, bot or Telegram on the feature one-shot path. The early argv bootstrap must exit before those module imports execute.
- Do not let payload/config choose OAuth client/authorize/token endpoint or effective home/path. Codex endpoints are fixed plugin constants; effective home is resolved once in backend; user-selected files use trusted native handles.
- Do not call OAuth token endpoint, refresh, account quota, or network login during structural import. OAuth network exchange only belongs to explicit OAuth flow and still must not auto-apply.
- Do not let save-dialog cancel become an error; do not write an export file before user confirmation/destination selection.
- Do not trust ZIP manifest paths, `relative_rollout_path`, `session_id`, title, or `cwd`; sanitize display values and validate write paths independently.
- Do not make a conflict “merge” by overwriting rollout/index. Same-id hash equality is skip; different hash is conflict.
- Do not permanently delete trash or add copy-to-instance/cross-instance/multiple Codex-home controls.
- Do not call `ps`, process inspection, Codex app-server, runtime reconnect, or metadata rebuild outside effective local feature scope. Cockpit has broader multi-instance behavior; D-12/D-26/D-32 narrow Phase 23.
- Do not claim AES-256-GCM is available from current stdlib. Current dependencies prove it is not; resolve the audited primitive before implementation.
- Do not run build/package/install/restart/packaged verification without explicit current-conversation permission (`AGENTS.md` and `OnlineWorker/AGENTS.md`).

## Validation Architecture

Validation must be layered, deterministic, and temporary-directory-only. No test may read or write the real `~/.codex`, `$CODEX_HOME`, `~/.Trash`, `~/.antigravity_cockpit`, or a user’s OnlineWorker data directory.

### Layer 1 — Pure contract/compatibility tests

Run Python unit tests for identity normalization/upsert, token/agent/API-key shape parsing, top-level array/object compatibility, unknown-field nested round-trip, invalid shape/version/missing identity, redaction, and error classification. Use synthetic secrets (`secret-token-A`, `sk-test-only`) that are asserted absent from list/log/diagnostic output.

Required Cockpit fixture assertions:

- one regular token export round-trips access/refresh/id/account fields;
- agent identity export has `auth_mode: agentIdentity` and no access token;
- API key export has `auth_mode: apikey` and `OPENAI_API_KEY`;
- single record exports as array under `cockpit_tools`;
- unknown top-level and nested fields survive import->internal->export;
- unsupported CPA/shape/version is rejected clearly, not returned as empty success.

Suggested command after implementation: `python3 -m pytest plugins/providers/builtin/codex/tests/test_account_compat.py plugins/providers/builtin/codex/tests/test_account_model.py`.

### Layer 2 — Crypto/storage/transaction tests

Use `tempfile.TemporaryDirectory()` and explicit `plugin_data_dir`. Assert:

- key is exactly 32 random bytes, stored mode 0600 where supported;
- detail ciphertext includes envelope metadata but not plaintext secret;
- decrypt round-trip preserves all JSON values and unknown fields;
- wrong key/tampered nonce/ciphertext/version fails without replacing file;
- plaintext legacy record migrates only after successful read and becomes encrypted;
- index/key/detail writes are atomic and backup is available after simulated replace failure;
- two concurrent mutation attempts serialize or one fails cleanly;
- permissions on index/detail/backup/export destination are user-only where filesystem allows.

The crypto implementation must have a dedicated test vector/round-trip test and dependency lock check. Do not “test” by reading a real user key.

Suggested command: `python3 -m pytest plugins/providers/builtin/codex/tests/test_account_store.py plugins/providers/builtin/codex/tests/test_apply.py`.

### Layer 3 — OAuth local protocol tests

No real browser, listener, or token endpoint. Feed a synthetic URL captured by the generic broker, plus manual callback strings, into the same complete action; use fake clock/state store and monkeypatched token opener. Assert PKCE verifier/challenge and state are present; exact state mismatch/empty code/expired state/cancel reject; full URL/path/query manual parsing accepts only supported forms; callback response/logging never contains code/verifier/token. Browser open is a recorded generic host capability, not launched by Python tests.

Suggested command: `python3 -m pytest plugins/providers/builtin/codex/tests/test_oauth.py`.

### Layer 4 — Effective-home apply tests

Create temp `codex_home` with synthetic `auth.json` and a separate `plugin_data_dir`; set `CODEX_HOME` only inside test process or pass explicit resolver. Test env-set precedence and no-env fallback through an injected home, never process-global real home. Assert:

- import leaves original auth/current marker unchanged;
- Apply writes only `auth.json` in target home and plugin marker/index;
- success is atomic and rereadable;
- failure at temp write/rename/read-back restores byte-for-byte old auth and prior current marker;
- no process scan, socket connect, EventBus event, notification, app-server call, or restart is invoked (inject spies/denylist).

Suggested command: `python3 -m pytest plugins/providers/builtin/codex/tests/test_apply.py`.

### Layer 5 — Session file/ZIP/trash/repair tests

Build a synthetic effective home with `sessions/`, `archived_sessions/`, `session_index.jsonl`, minimal rollout JSONL, plus required `<home>/state_5.sqlite` and `<home>/sqlite/state_5.sqlite` fixtures. Cover:

- title search and expandable row metadata;
- 30-day boundary inclusion/exclusion, duplicate snapshot dedup, fork replay handling, cost unavailable state;
- export exact manifest keys/kind/version/path/hash/size and deterministic safe file entries;
- import valid package, same-id same-hash skip, same-id different-hash conflict, bad hash, malformed manifest/version, absolute/`..`/colon/symlink path, size mismatch, and index-write failure rollback;
- trash writes manifest and moves file without permanent deletion;
- restore verifies session id/path, handles target conflict, restores index/mtime, and leaves trash on failure;
- current quick visibility repair reads `config.toml.model_provider` (default `openai`), updates only existing official `threads.model_provider` rows and referenced rollout first-line `session_meta`, ignores `sqlite/codex-dev.db`/session index/timestamps, and covers no-op/success/failure rollback with no EventBus/session/notification side effect.

Suggested command: `python3 -m pytest plugins/providers/builtin/codex/tests/test_session_assets.py`.

### Layer 6 — Generic host/IPC/UI tests

Rust tests cover account-feature manifest discovery, duplicate/invalid feature isolation, opaque action routing, timeout/error redaction, and save/browser/file capability cancellation. Frontend Node/Vite tests cover no-feature hidden sidebar, one generic account entry, selector loading disabled + `aria-live`, one plugin failure not blocking another, metadata-driven mount without provider-id branch, and secret-free list DTO. Reuse existing test style (`plugins/providers/DEVELOPMENT.md:247-255` and `:250` cargo command pattern; `23-UI-SPEC.md` acceptance matrix).

Suggested commands (after implementation):

```bash
python3 -m pytest plugins/providers/builtin/codex/tests
cargo test --manifest-path mac-app/src-tauri/Cargo.toml account_feature --lib
cd mac-app && npm run build
```

`npm run build` is source/frontend verification only; packaging, DMG creation, install, launch, and packaged-app verification remain prohibited until explicitly authorized. The user later granted build/package/DMG-launch permission on 2026-08-18; see `23-VALIDATION.md` for the executed boundary. If a test harness needs `HOME`, `CODEX_HOME`, or process env, set/restore it in a scoped fixture and assert the real home was not touched.

## Planning recommendations

1. Plan the generic host seam first, but keep its contract to discovery, selector, mount, opaque action, and native system capabilities. Add no future-provider registry, schema, or account abstraction beyond what Codex needs.
2. Plan Codex backend as independent offline feature modules: compat/model -> encrypted store -> OAuth -> apply -> sessions/ZIP/trash/repair. Keep every mutation behind a per-plugin lock and explicit rollback boundary.
3. Use the audited `cryptography==48.0.1` candidate above for the plugin-owned AES-256-GCM implementation, but place a blocking user-confirmation checkpoint before changing `requirements.txt`; packaging inclusion remains unverified until build/package permission is granted.
4. Pin Cockpit fixtures at commit `35963163813d7424b63cd6053874ce5fc7973d03` in synthetic tests, with a short format note. Do not vendor Cockpit source or copy implementation.
5. Parameterize `effective_codex_home` in all Codex parsers before adding session operations; add a test fixture that fails if any code opens literal `~/.codex`.
6. Implement and test account import/apply/export before session asset UI. The acceptance contract must distinguish import success, Apply success, external matched, and external unmanaged.
7. Keep frontend all under `plugins/providers/builtin/codex/frontend/`; use a build-time entry contract because current Vite/Tauri resource staging cannot load arbitrary runtime React. Defer overlay frontend staging design until another plugin actually needs it.
8. Make the validation plan a deliverable: unit/crypto/OAuth/apply/session/host layers above, exact commands, synthetic secrets, temp dirs, and an explicit no-real-`~/.codex` guard.

## Explicitly out of scope

The implemented D-38..D-40 boundary allows only an explicit user-triggered read of the fixed official Codex usage endpoint. It still excludes background quota polling, subscription management beyond those returned usage windows, account tags/notes/groups, auto-rotation, API gateway/relay, API service keys, account pools/load balancing, model-provider management, wake-up tasks, multi-open, automatic account switching, Claude/Codemaker implementations, copy-to-instance, cross-instance sync, multiple named Codex homes, permanent session deletion, OnlineWorker live provider/session behavior, Task Board/EventBus/notification integration, app-server lifecycle/restart/reconnect, and any Cockpit live datastore or source-code reuse.
