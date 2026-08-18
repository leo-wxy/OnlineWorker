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
| T23-01 | credential import/store/export/logging | secret 只在显式 backend action 边界出现；list/diagnostic/log 全部脱敏；detail AES-256-GCM 加密 |
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
| 23-03-* | generic host transport | 2 | D-01–D-05, D-07, D-37, D-40 | T23-01–T23-06 | early one-shot import graph、opaque action、host data root、loopback、one-use open/save handle、错误脱敏 | Python + Rust unit | `python3 -m pytest tests/test_account_features.py -q && cargo test --manifest-path mac-app/src-tauri/Cargo.toml account_feature --lib` | ✅ | ✅ green |
| 23-04-* | frontend host | 3 | D-01, D-03–D-07, D-33, D-37, D-40 | T23-05 | 动态单入口、builtin source root、descriptor/build-registry exact mount、overlay/mismatch isolation | Node contract + typecheck | `cd mac-app && node --test tests/accountFeatureHost.test.mjs && ./node_modules/.bin/tsc --noEmit` | ✅ | ✅ green |
| 23-05-* | compat/model | 1 | D-08–D-09, D-14–D-15, D-17–D-21, D-24–D-25 | T23-01, T23-03 | Cockpit shape/identity/upsert/unknown-field round-trip，secret-free DTO | Python unit | `python3 -m pytest plugins/providers/builtin/codex/tests/test_account_compat.py plugins/providers/builtin/codex/tests/test_account_model.py -q` | ✅ | ✅ green |
| 23-06-* | encrypted store | 2 | D-13–D-14, D-19, D-22–D-25 | T23-01, T23-04, T23-06 | AES-GCM、0600、atomic/migration、shared cross-process lock、真实目录拒绝 | Python unit | `python3 -m pytest plugins/providers/builtin/codex/tests/test_account_store.py -q` | ✅ | ✅ green |
| 23-07-* | OAuth/action | 3 | D-08–D-12, D-20, D-24–D-25, D-40 | T23-01–T23-06 | fixed official endpoint/client、PKCE/state、fake exchange、trusted open handle、path override reject、不 apply | Python protocol | `python3 -m pytest plugins/providers/builtin/codex/tests/test_oauth.py -q` | ✅ | ✅ green |
| 23-08-* | apply/export | 4 | D-08, D-11–D-20, D-22–D-25, D-40 | T23-01, T23-04, T23-06 | backend-resolved effective home、rollback、external match、trusted save full export、action wiring | Python transaction | `python3 -m pytest plugins/providers/builtin/codex/tests/test_apply.py plugins/providers/builtin/codex/tests/test_account_export.py -q` | ✅ | ✅ green |
| 23-09-* | session backend | 5 | D-26–D-32, D-40 | T23-03, T23-04, T23-06 | 30d、trusted ZIP handles、conflict/trash、shared lock、exact current quick repair/rollback | Python file/archive | `python3 -m pytest plugins/providers/builtin/codex/tests/test_session_assets.py -q` | ✅ | ✅ green |
| 23-10-* | account UI | 5 | D-03–D-06, D-08–D-09, D-15–D-19, D-24, D-33–D-35, D-37 | T23-01–T23-06 | 四 tab、explicit Apply/reapply/export/quota refresh、trusted handles、secret/path-free state | Node contract + typecheck | `cd mac-app && node --test tests/accountFeatureCodex.test.mjs tests/accountFeatureHost.test.mjs && ./node_modules/.bin/tsc --noEmit` | ✅ | ✅ green |
| 23-11-* | session UI | 6 | D-26–D-33, D-36–D-37, D-40 | T23-03, T23-04, T23-06 | 单页层级、cwd group → conversation rows、ZIP open/save handle、可逆操作、accessibility/responsive | Node contract + typecheck | `cd mac-app && node --test tests/accountFeatureCodex.test.mjs tests/accountFeatureHost.test.mjs && ./node_modules/.bin/tsc --noEmit` | ✅ | ✅ green |
| 23-12-* | integration/regression | 7 | D-01–D-40 | T23-01–T23-06 | early import、enabled discovery、entry agreement、fixed OAuth/quota endpoints、trusted paths、shared lock、无 live coupling | Python + Rust + Node + TypeScript | `python3 -m pytest tests/test_account_features.py tests/test_packaging_socks_support.py plugins/providers/builtin/codex/tests -q && cargo test --manifest-path mac-app/src-tauri/Cargo.toml account_feature --lib && cd mac-app && node --test tests/accountFeature*.test.mjs && ./node_modules/.bin/tsc --noEmit` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

表中 plan/task id 与已定稿的 `23-01`–`23-12` 对齐，不得降低 D-01–D-40 和 T23-01–T23-06 覆盖。

## Wave 0 Requirements

- [x] `plugins/providers/builtin/codex/tests/conftest.py` — synthetic credentials、explicit `plugin_data_dir`、effective-home/tempdir guard，在测试末断言真实 home 未被触碰。
- [x] `plugins/providers/builtin/codex/tests/test_account_compat.py` — Cockpit commit-pinned object/array/token/agent/API-key/unknown-field fixtures。
- [x] `plugins/providers/builtin/codex/tests/test_account_model.py` — identity normalization、dedupe/upsert、redacted DTO。
- [x] `plugins/providers/builtin/codex/tests/test_account_store.py` — AES-GCM vector/round-trip/tamper、0600、atomic/backup/migration/concurrency。
- [x] `plugins/providers/builtin/codex/tests/test_oauth.py` — synthetic captured/manual callback、fake clock/token opener、fixed endpoint/client、PKCE/state/exchange/trusted open handle。
- [x] `plugins/providers/builtin/codex/tests/test_apply.py` 与 `test_account_export.py` — import/apply separation、backend home resolution、byte rollback、trusted save handle、no-process-side-effects。
- [x] `plugins/providers/builtin/codex/tests/test_quota.py` — fixed official usage endpoint、token refresh/retry、usage-window parser 与错误保留。
- [x] `plugins/providers/builtin/codex/tests/test_session_assets.py` — synthetic rollout/index/ZIP/trash、conversation kind、cwd grouping、official state DB/current quick repair、shared-lock fixtures。
- [x] `plugins/providers/builtin/codex/tests/test_phase23_boundaries.py` — real-path/forbidden-live/fixed-endpoint/lock/repair-scope phase guard。
- [x] `mac-app/src-tauri` account-feature tests — independent loader、early import graph、opaque action、host data root、loopback broker、one-use native handles。
- [x] `mac-app/tests/accountFeatureHost.test.mjs` 与 `accountFeatureCodex.test.mjs` — sidebar/selector/plugin isolation/UI state/secret-free contract。
- [x] `mac-app/tests/accountFeatureRegression.test.mjs` — manifest/build entry agreement、overlay exclusion、no frontend secret/path persistence、forbidden-scope guard。

复用现有 pytest、Rust 和 Node test 基础设施；不新增测试框架。AES-256-GCM 原语依赖是实现前必须明确批准的产品依赖变更，不得以测试 helper 替代生产实现。

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| system browser OAuth 与 loopback/manual callback UX | D-09–D-10, D-33–D-37 | 真实浏览器、焦点恢复和 macOS callback 需要安装态，且会涉及真实账号 | 仅在用户当前对话明确授权 build/package/install/launch 与测试账号后执行；验证四 tab、browser open、callback/fallback、Escape/focus restore |
| light/dark/system、窄屏和 keyboard 视觉验证 | D-03–D-08, D-33–D-37 | 视觉层级、focus ring、换行和 native dialog 无法完全由 source contract 证明 | 获得明确安装态验证授权后，按 `23-UI-SPEC.md` Acceptance State Matrix 逐项核对 |
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

## Validation Sign-Off

- [x] 所有规划能力都有自动验证层或 Wave 0 依赖
- [x] Sampling continuity：不存在连续 3 个任务没有自动验证
- [x] Wave 0 覆盖全部当前 MISSING 测试文件
- [x] 不使用 watch-mode flags
- [x] 定向反馈延迟目标低于 30 秒，全量目标低于 120 秒
- [x] `nyquist_compliant: true` 与 `wave_0_complete: true` 已设置

**Approval:** source/package/read-only DMG QA passed 2026-08-18; real account/session mutations remain unverified
