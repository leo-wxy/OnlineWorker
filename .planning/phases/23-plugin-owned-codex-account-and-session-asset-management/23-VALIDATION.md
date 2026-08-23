---
phase: 23
slug: plugin-owned-codex-account-and-session-asset-management
status: passed
nyquist_compliant: true
wave_0_complete: true
created: 2026-08-17
---

# Phase 23 — Validation Strategy

> Phase 23 的反馈采样契约。所有凭据、Codex Home、OAuth 和会话资产验证必须使用 synthetic fixture 与临时目录；不得读写用户真实 `~/.codex`、`$CODEX_HOME`、Trash、Cockpit 或 OnlineWorker data dir。

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Python `pytest` + Rust `cargo test` + Node.js built-in `node:test` + TypeScript typecheck |
| **Config file** | 现有 `pytest.ini`/project pytest discovery、`mac-app/src-tauri/Cargo.toml`、`mac-app/package.json` |
| **Quick run command** | `python3 -m pytest plugins/providers/builtin/codex/tests/test_account_compat.py plugins/providers/builtin/codex/tests/test_account_store.py plugins/providers/builtin/codex/tests/test_apply.py plugins/providers/builtin/codex/tests/test_quota.py -q` |
| **Full suite command** | `python3 -m pytest tests/test_account_features.py tests/test_packaging_socks_support.py plugins/providers/builtin/codex/tests -q && cargo test --manifest-path mac-app/src-tauri/Cargo.toml account_feature --lib && cd mac-app && node --test tests/accountFeature*.test.mjs && ./node_modules/.bin/tsc --noEmit` |
| **Estimated runtime** | quick ~30s；full ~120s（以本机实测为准） |

## Sampling Rate

- **After every task commit:** 运行覆盖该任务的最小 Python/Rust/Node test，并运行 `git diff --check`。
- **After every plan wave:** 运行当前已存在的 Phase 23 全量测试；波次末扩展到 TypeScript typecheck。
- **Before `$gsd-verify-work`:** full suite 必须为 green，且无任何测试路径命中真实 home/data dir。
- **Max feedback latency:** 定向测试目标 30 秒，波次全量验证目标 120 秒。

## Threat References

| Threat | Boundary | Required secure behavior |
|--------|----------|--------------------------|
| T23-01 | credential import/store/export/logging/cache | secret 只在显式 backend action 边界出现；list/diagnostic/log 全部脱敏；frontend cache 只允许版本化 display-field allowlist；detail AES-256-GCM 加密 |
| T23-02 | OAuth browser/callback | generic host 只做 loopback capture；plugin 使用固定 official endpoint/client 做 PKCE/state/exchange；callback/secret 不记录或持久化 |
| T23-03 | imported JSON/ZIP/native path | 结构、版本、identity、hash、size、relative path 校验；文件只经 feature/mode/expiry-bound one-use handle；拒绝 traversal/symlink |
| T23-04 | index/detail/auth/session mutation | 同一个 cross-process lock；same-directory temp + fsync/replace/SQLite transaction + bounded backup；失败恢复 |
| T23-05 | plugin/host boundary | independent enabled builtin discovery、entry registry agreement、无 Codex 特判；overlay/missing/plugin failure 隔离 |
| T23-06 | local filesystem scope | data root 由 host 注入，effective home 由 backend 一次解析；payload 无路径权；deny real home/Trash/data dir |

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 23-01-01 | dependency/config gate | 1 | D-03, D-37, D-22–D-25 | T23-01, T23-05 | 未经明确确认不修改/安装 cryptography，也不改 Vite/TypeScript plugin source root | Human checkpoint | 明确确认三文件变更、影响与回滚面 | ✅ | ✅ green |
| 23-02-* | generic discovery | 1 | D-01, D-03–D-07, D-37 | T23-05 | independent enabled builtin loader、overlay exclusion、entry containment、无 provider registry/live import | Python contract | `python3 -m pytest tests/test_account_features.py -q` | ✅ | ✅ green |
| 23-03-* | generic host transport | 2 | D-01–D-05, D-07, D-37, D-40 | T23-01–T23-06 | early long-lived JSONL worker、request binding、opaque action、host data root、loopback、one-use open/save handle、timeout/crash lazy restart、no replay、错误脱敏 | Python + Rust unit | `python3 -m pytest tests/test_account_features.py -q && cargo test --manifest-path mac-app/src-tauri/Cargo.toml account_feature --lib` | ✅ | ✅ green |
| 23-04-* | frontend host | 3 | D-01, D-03–D-07, D-33, D-37, D-40 | T23-05 | 动态单入口、builtin source root、descriptor/build-registry exact mount、overlay/mismatch isolation | Node contract + typecheck | `cd mac-app && node --test tests/accountFeatureHost.test.mjs && ./node_modules/.bin/tsc --noEmit` | ✅ | ✅ green |
| 23-05-* | compat/model | 1 | D-08–D-09, D-14–D-15, D-17–D-21, D-24–D-25 | T23-01, T23-03 | Cockpit shape/identity/upsert/unknown-field round-trip，secret-free DTO | Python unit | `python3 -m pytest plugins/providers/builtin/codex/tests/test_account_compat.py plugins/providers/builtin/codex/tests/test_account_model.py -q` | ✅ | ✅ green |
| 23-06-* | encrypted store | 2 | D-13–D-14, D-19, D-22–D-25 | T23-01, T23-04, T23-06 | AES-GCM、0600、atomic/migration、shared cross-process lock、真实目录拒绝 | Python unit | `python3 -m pytest plugins/providers/builtin/codex/tests/test_account_store.py -q` | ✅ | ✅ green |
| 23-07-* | OAuth/action | 3 | D-08–D-12, D-20, D-24–D-25, D-40 | T23-01–T23-06 | fixed official endpoint/client、PKCE/state、fake exchange、Token/JSON import、path override reject、不 apply | Python protocol | `python3 -m pytest plugins/providers/builtin/codex/tests/test_oauth.py -q` | ✅ | ✅ green |
| 23-08-* | apply/export | 4 | D-08, D-11–D-20, D-22–D-25, D-40 | T23-01, T23-04, T23-06 | backend-resolved effective home、rollback、external match、trusted save full export、action wiring | Python transaction | `python3 -m pytest plugins/providers/builtin/codex/tests/test_apply.py plugins/providers/builtin/codex/tests/test_account_export.py -q` | ✅ | ✅ green |
| 23-09-* | session backend | 5 | D-26–D-32, D-40 | T23-03, T23-04, T23-06 | 30d、trusted ZIP handles、conflict/trash、shared lock、exact current quick repair/rollback | Python file/archive | `python3 -m pytest plugins/providers/builtin/codex/tests/test_session_assets.py -q` | ✅ | ✅ green |
| 23-10-* | account UI | 5 | D-03–D-06, D-08–D-09, D-15–D-19, D-24, D-33–D-35, D-37 | T23-01–T23-06 | OAuth/Token JSON 双 tab、导入/应用两步空态、响应式单层卡片、移除 API Key/file actions、cache-first/background calibration、versioned redacted allowlist、explicit Apply/reapply/export/quota refresh、secret/path-free state | Node contract + typecheck | `cd mac-app && node --test tests/accountFeatureCodex.test.mjs tests/accountFeatureHost.test.mjs && ./node_modules/.bin/tsc --noEmit` | ✅ | ✅ green |
| 23-11-* | session UI | 6 | D-26–D-33, D-36–D-37, D-40 | T23-03, T23-04, T23-06 | 单页层级、cwd group → conversation rows、ZIP open/save handle、可逆操作、accessibility/responsive | Node contract + typecheck | `cd mac-app && node --test tests/accountFeatureCodex.test.mjs tests/accountFeatureHost.test.mjs && ./node_modules/.bin/tsc --noEmit` | ✅ | ✅ green |
| 23-12-* | integration/regression | 7 | D-01–D-40 | T23-01–T23-06 | early import、enabled discovery、entry agreement、fixed OAuth/quota endpoints、trusted paths、shared lock、无 live coupling | Python + Rust + Node + TypeScript | `python3 -m pytest tests/test_account_features.py tests/test_packaging_socks_support.py plugins/providers/builtin/codex/tests -q && cargo test --manifest-path mac-app/src-tauri/Cargo.toml account_feature --lib && cd mac-app && node --test tests/accountFeature*.test.mjs && ./node_modules/.bin/tsc --noEmit` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

表中 plan/task id 与已定稿的 `23-01`–`23-12` 对齐，不得降低 D-01–D-40 和 T23-01–T23-06 覆盖。

## Wave 0 Requirements

- [x] `plugins/providers/builtin/codex/tests/conftest.py` — synthetic credentials、explicit `plugin_data_dir`、effective-home/tempdir guard，在测试末断言真实 home 未被触碰。
- [x] `plugins/providers/builtin/codex/tests/test_account_compat.py` — Cockpit commit-pinned object/array/token/agent/API-key/unknown-field fixtures。
- [x] `plugins/providers/builtin/codex/tests/test_account_model.py` — identity normalization、dedupe/upsert、redacted DTO。
- [x] `plugins/providers/builtin/codex/tests/test_account_store.py` — AES-GCM vector/round-trip/tamper、0600、atomic/backup/migration/concurrency。
- [x] `plugins/providers/builtin/codex/tests/test_oauth.py` — synthetic captured/manual callback、fake clock/token opener、fixed endpoint/client、PKCE/state/exchange。
- [x] `plugins/providers/builtin/codex/tests/test_apply.py` 与 `test_account_export.py` — import/apply separation、backend home resolution、byte rollback、trusted save handle、no-process-side-effects。
- [x] `plugins/providers/builtin/codex/tests/test_quota.py` — fixed official usage endpoint、token refresh/retry、usage-window parser 与错误保留。
- [x] `plugins/providers/builtin/codex/tests/test_session_assets.py` — synthetic rollout/index/ZIP/trash、conversation kind、cwd grouping、official state DB/current quick repair、shared-lock fixtures。
- [x] `plugins/providers/builtin/codex/tests/test_phase23_boundaries.py` — real-path/forbidden-live/fixed-endpoint/lock/repair-scope phase guard。
- [x] `mac-app/src-tauri` account-feature tests — independent loader、early multi-request worker、request-bound response、opaque action、host data root、loopback broker、one-use native handles。
- [x] `mac-app/tests/accountFeatureHost.test.mjs` 与 `accountFeatureCodex.test.mjs` — sidebar/selector/plugin isolation/UI state/secret-free contract。
- [x] `mac-app/tests/accountFeatureRegression.test.mjs` — manifest/build entry agreement、overlay exclusion、versioned redacted summary cache、no frontend secret/path persistence、forbidden-scope guard。

复用现有 pytest、Rust 和 Node test 基础设施；不新增测试框架。AES-256-GCM 原语依赖是实现前必须明确批准的产品依赖变更，不得以测试 helper 替代生产实现。

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| system browser OAuth 与 loopback/manual callback UX | D-09–D-10, D-33–D-37 | 真实浏览器、焦点恢复和 macOS callback 需要安装态，且会涉及真实账号 | 仅在用户当前对话明确授权 build/package/install/launch 与测试账号后执行；验证双 tab、browser open、全阶段可取消/关闭、callback/fallback、localhost 确认页、Escape/focus restore |
| light/dark/system、窄屏和 keyboard 视觉验证 | D-03–D-08, D-33–D-37 | 视觉层级、focus ring、换行和 native dialog 无法完全由 source contract 证明 | 获得明确安装态验证授权后，按 `23-UI-SPEC.md` Acceptance State Matrix 逐项核对；账号页分别验证 empty 与 populated 状态，确认分栏降级、卡片高度、额度分隔和底部操作对齐 |
| native file/save dialog cancel 与目标权限 | D-16, D-28–D-30 | macOS picker/save dialog 的真实行为需要安装态 | 仅在获授权的临时目录内导入/导出 synthetic fixture；取消不显示错误，不读写真实 home |
| Vite source build 与 packaged-app 回归 | D-01–D-40 | 仓库规则要求当前对话明确授权 build/package/install/launch | ✅ 用户授权后由 combined wrapper 完成 build/package；挂载 DMG 并只读检查折叠侧栏、账号、确认框、native save panel、额度入口和 cwd group → conversation 展开结构。未安装到 `/Applications` |

## Execution Evidence — 2026-08-18

- `python3 -m pytest tests/test_account_features.py tests/test_packaging_socks_support.py plugins/providers/builtin/codex/tests -q` — **51 passed**。
- `cargo test --manifest-path mac-app/src-tauri/Cargo.toml account_feature --lib` — **11 passed**。
- `cd mac-app && node --test tests/accountFeature*.test.mjs tests/appShell.test.mjs tests/theme.test.mjs tests/themeContract.test.mjs` — **40 passed**。
- `cd mac-app && ./node_modules/.bin/tsc --noEmit` — passed。
- `git diff --check` — passed。
- `bash build.sh`（combined shell）— passed；生成 39 MB `OnlineWorker_1.9.0_aarch64.dmg`，SHA-256 `9c623489c0e31c677d39fa505f52835dd738bd82bb7f9a62fa1c959934e8713a`。
- Mounted-DMG sidebar QA — passed：`2041 x 560` 短窗口中导航区域可独立滚动、滚动条 chrome 隐藏、底部语言入口固定；恢复到 `1493 x 768` 后折叠态无裁切和大号装饰卡片。
- Mounted-DMG account QA — passed：当前 PRO 账号、35% 周额度、enabled reapply/quota/export actions 可见；reapply 打开可访问确认框；export 打开默认名 `codex-accounts.json` 的 native save panel，取消后账号列表仍保留 1 条。
- Mounted-DMG session QA — passed：30 天统计加载完成，**31 个 cwd/project 组 → 72 条 conversation** 可见；展开 `onlineworker-combined` 后会话明细正常呈现。
- 未执行：真实 OAuth、真实额度网络请求、真实 apply/reapply 确认、凭据文件写出、账号/会话导入、trash/restore/repair、安装到 `/Applications`。

### Account loading performance follow-up — 2026-08-18

- `python3 -m pytest tests/test_account_features.py plugins/providers/builtin/codex/tests -q` — **47 passed**；覆盖同一 early worker 内连续 list/action、request id 绑定、EOF 退出、live runtime 零导入及 Codex 后端回归。
- `cargo test --manifest-path mac-app/src-tauri/Cargo.toml account_feature --lib` — **10 passed**；覆盖 worker response 边界、timeout/error 映射、native capability 与 loopback。
- `node --test mac-app/tests/accountFeature*.test.mjs` — **10 passed**；覆盖 cache-first、后台校准、字段白名单、secret/path 禁止项及通用 host 边界。
- `cd mac-app && npm run build` — passed；TypeScript 与 Vite production build 均通过。
- `bash verify-packaged-fast.sh` — passed in **113 s**；重新构建 39 MB `OnlineWorker_1.9.0_aarch64.dmg`，SHA-256 `6c1a6b0ae4b40e41196fe1897a4074f930e12f5d2e2a1e96120e75e0e8a38472`，安装到 `/Applications` 后 app、bot、Codemaker 与 POPO bundled plugins 验证通过。
- Installed account cache-hit path — **449 ms** 内账号行可见，未出现 loading placeholder；后台校准继续运行。
- Installed resident worker — 同一 PyInstaller worker process tree 在账号/会话导航后持续存活，没有按 action 新建额外 worker tree。
- Installed session baseline — 刷新 **32 个工作目录 / 74 个会话** 用时 **6001 ms**；会话扫描未包含在本次 1、2 优化中，仍是独立性能缺口。
- 未主动执行 OAuth、apply/reapply、凭据导入导出或会话资产 mutation；因此这些 action 的安装包时延不作结论。

### Account UI and localhost callback follow-up — 2026-08-23

- 账号列表改为响应式卡片网格；窄屏自动单列，卡内身份、额度和操作保持稳定层级。
- OAuth 弹窗在 begin/open/wait/exchange 全阶段允许取消或关闭；过期异步结果不会关闭后来重新打开的弹窗。
- localhost 回调确认页使用 provider-neutral 的 OnlineWorker 文案，不显示 callback 参数或凭据；桌面与窄屏 source preview 已核对。
- 当前会话与废纸篓搜索统一由插件后端匹配标题、工作目录和 session id。
- `python3 -m pytest tests/test_account_features.py tests/test_packaging_socks_support.py tests/test_codex_runtime.py plugins/providers/builtin/codex/tests -q` — **71 passed**。
- `cargo test --manifest-path mac-app/src-tauri/Cargo.toml account_feature --lib` — **10 passed**；`cargo fmt --manifest-path mac-app/src-tauri/Cargo.toml --check` — passed。
- `cd mac-app && node --test tests/accountFeature*.test.mjs` — **10 passed**；`./node_modules/.bin/tsc --noEmit` — passed。
- `git diff --check` — passed。
- `bash build.sh` — passed；生成 `OnlineWorker_1.9.0_aarch64.dmg`，SHA-256 `aea1e9baeb4fa598201d332cd9dcb5aa626866abc6afb03b8c5e9f10c1f2ead7`。
- `bash verify-packaged-fast.sh` 的重建和 DMG 校验通过；安装步骤发现两个已运行 3 天且不响应 SIGTERM 的旧 bot，因此脚本在覆盖安装前按预期失败。按明确 PID 强制停止旧实例后，`OnlineWorker/scripts/install-current-dmg.sh` 成功完成安装和重启；DMG 与 `/Applications` 内 app、bot、ccusage 哈希完全一致。
- Installed-app read-only QA — 账号卡片显示 1 个当前 PRO 账号与 68% 周额度；添加账号弹窗双 tab、`关闭`、`取消`均可用；会话页扫描完成后显示 **35 个工作目录 / 79 个会话**。Codemaker 与 POPO bundled plugin manifest 存在，localhost callback 模板已嵌入应用二进制。
- 未运行真实 OAuth，也未执行 apply/reapply、额度网络刷新、账号导入导出或会话 mutation。

### Account tab visual-system follow-up — 2026-08-23

- 保留账号页头、`账号 / 会话资产` 分段控件、工具栏和所有现有业务 action；只重排账号 Tab 内的 loading、empty、toolbar 与 account-card presentation。
- Empty state 改为左侧主行动和右侧 `01 安全导入 / 02 手动应用` 两步说明；窄屏降为上下结构，不再使用大面积居中占位卡。
- Account card 改为 16px 圆角单层 surface，固定“身份与状态 → 额度 → 操作”顺序；metadata 合并为紧凑行，额度窗口以 hairline 分隔，当前账号只使用蓝色内侧边和轻量背景强调。
- `cd mac-app && node --test tests/accountFeature*.test.mjs` — **11 passed**。
- `cd mac-app && ./node_modules/.bin/tsc --noEmit` — passed；`pnpm build` — passed；`git diff --check` — passed。
- 本地 HTML 状态板在 1300 × 768 视口直接加载 production build 的全局主题 CSS 与 Codex plugin CSS，使用合成数据覆盖账号空态、账号卡片、OAuth、Token / JSON、会话工程卡片和会话选择弹窗；支持 Light/Dark、宽/窄布局切换，用户已确认采用该视觉方向。
- 尚未重新打包或安装；empty/populated 的 installed-app Light/Dark 同尺寸视觉对比仍为 manual-only pending。

### Session project-card picker follow-up — 2026-08-23

- 会话一级视图改为 `cwd`/project 卡片；卡片只显示项目摘要与最近会话，底部统一提供 `选择会话`。
- 选择弹窗复用现有 `selected: Set<sessionId>`，支持 title/session id 搜索、全选当前结果、逐条选择、取消不提交和确认后仅替换当前工程选择。
- `cd mac-app && node --test tests/accountFeature*.test.mjs` — **10 passed**。
- `cd mac-app && ./node_modules/.bin/tsc --noEmit` — passed。
- `git diff --check` — passed。
- `bash build.sh` — passed；生成 40,896,350-byte `OnlineWorker_1.9.0_aarch64.dmg`，SHA-256 `ae1802ddd9bd0a900a42d3761f12b7bc493f5d738db288c6094ccc4521e92101`。
- `bash verify-packaged-fast.sh` — build、DMG 校验通过；首次安装被两个不响应 SIGTERM 的旧 bot 阻塞。按明确 PID 停止旧实例后，`OnlineWorker/scripts/install-current-dmg.sh` 安装、重启通过，DMG 与安装版 app/bot/ccusage 哈希一致，Codemaker/POPO bundled manifests 存在。
- Installed-app UI — 35 个工作目录 / 79 个会话正常加载；工程卡片底部 `选择会话` 对齐；弹窗搜索、全选、逐项选择、取消不提交、确认后 scoped selection 均通过。桌面 `1493 x 768` 与 Variant C 并排检查无 P0/P1/P2 问题。
- 未执行真实会话导入、导出、移入废纸篓、恢复或 visibility repair mutation。

## Validation Sign-Off

### Review remediation follow-up — 2026-08-23

- OAuth 取消改为 operation-scoped one-shot sidecar；token exchange 不再占用落盘锁，账号写入前重新校验 pending operation。关闭弹窗、切页卸载、旧 cancel 和旧 error callback 均有回归覆盖。
- 当前会话与废纸篓统一在插件后端匹配 title、cwd 和 session id；前端重复过滤已移除。
- localhost 页面改为中性“回调已接收”文案，清除地址栏 query，不再宣称授权成功。
- `PYTHONPATH=. pytest -q tests/test_account_features.py tests/test_packaging_socks_support.py tests/test_codex_runtime.py plugins/providers/builtin/codex/tests` — **75 passed**。
- `cargo test --manifest-path mac-app/src-tauri/Cargo.toml account_feature --lib` — **13 passed**。
- `node --test mac-app/tests/accountFeatureHost.test.mjs mac-app/tests/accountFeatureCodex.test.mjs mac-app/tests/accountFeatureRegression.test.mjs` — **11 passed**；TypeScript 与 Rust format checks passed。
- `bash scripts/verify-packaged-fast.sh` — **passed in 97s**；生成并安装 `OnlineWorker_1.9.0_aarch64.dmg`，SHA-256 `8e81ced0429e707e4709f69f6a7750ff7652a316b3595de873e68750e89e983c`；DMG 与 `/Applications` 的 app/bot/ccusage hashes 一致。
- 安装版已重启：`onlineworker-app` PID `48647`、account worker PID `48707`，进程路径均位于 `/Applications/OnlineWorker.app`。未运行真实 OAuth/账号 mutation。

- [x] 所有规划能力都有自动验证层或 Wave 0 依赖
- [x] Sampling continuity：不存在连续 3 个任务没有自动验证
- [x] Wave 0 覆盖全部当前 MISSING 测试文件
- [x] 不使用 watch-mode flags
- [x] 定向反馈延迟目标低于 30 秒，全量目标低于 120 秒
- [x] `nyquist_compliant: true` 与 `wave_0_complete: true` 已设置

**Approval:** source/package/installed-app read-only QA passed 2026-08-23; session card-picker packaged visual and selection-state QA passed, real account/session mutations remain unverified
