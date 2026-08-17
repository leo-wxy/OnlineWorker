---
phase: 23
slug: plugin-owned-codex-account-and-session-asset-management
status: approved
nyquist_compliant: true
wave_0_complete: false
created: 2026-08-17
---

# Phase 23 — Validation Strategy

> Phase 23 的反馈采样契约。所有凭据、Codex Home、OAuth 和会话资产验证必须使用 synthetic fixture 与临时目录；不得读写用户真实 `~/.codex`、`$CODEX_HOME`、Trash、Cockpit 或 OnlineWorker data dir。

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Python `pytest` + Rust `cargo test` + Node.js built-in `node:test` + TypeScript/Vite source build |
| **Config file** | 现有 `pytest.ini`/project pytest discovery、`mac-app/src-tauri/Cargo.toml`、`mac-app/package.json` |
| **Quick run command** | `python3 -m pytest plugins/providers/builtin/codex/tests/test_account_compat.py plugins/providers/builtin/codex/tests/test_account_store.py plugins/providers/builtin/codex/tests/test_apply.py -q` |
| **Full suite command** | `python3 -m pytest plugins/providers/builtin/codex/tests && cargo test --manifest-path mac-app/src-tauri/Cargo.toml account_feature --lib && cd mac-app && node --test tests/accountFeature*.test.mjs && ./node_modules/.bin/tsc --noEmit && pnpm build` |
| **Estimated runtime** | quick ~30s；full ~120s（以本机实测为准） |

## Sampling Rate

- **After every task commit:** 运行覆盖该任务的最小 Python/Rust/Node test，并运行 `git diff --check`。
- **After every plan wave:** 运行当前已存在的 Phase 23 全量测试；波次末再扩展到 TypeScript/Vite source build。
- **Before `$gsd-verify-work`:** full suite 必须为 green，且无任何测试路径命中真实 home/data dir。
- **Max feedback latency:** 定向测试目标 30 秒，波次全量验证目标 120 秒。

## Threat References

| Threat | Boundary | Required secure behavior |
|--------|----------|--------------------------|
| T23-01 | credential import/store/export/logging | secret 只在显式 backend action 边界出现；list/diagnostic/log 全部脱敏；detail AES-256-GCM 加密 |
| T23-02 | OAuth browser/callback | PKCE + state；loopback/manual callback 均验证 state；不记录 code/verifier/token |
| T23-03 | imported JSON/ZIP/path | 结构、版本、identity、hash、size、relative path 校验；拒绝 absolute/`..`/colon/symlink traversal |
| T23-04 | index/detail/auth/session mutation | same-directory temp + fsync/replace + bounded backup；失败恢复字节与 current marker |
| T23-05 | plugin/host boundary | host 只做 discovery/mount/opaque action/system capability；无 Codex 特判；单插件失败隔离 |
| T23-06 | local filesystem scope | effective home 一次解析并显式传递；测试 deny real `~/.codex`/Trash/data dir |

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 23-01-* | host seam | 1 | D-01–D-08, D-39–D-40 | T23-05 | 通用 discovery/mount/action；无 provider-id 特判；错误隔离 | Rust + Node contract | `cargo test --manifest-path mac-app/src-tauri/Cargo.toml account_feature --lib && cd mac-app && node --test tests/accountFeatureHost.test.mjs` | ❌ W0 | ⬜ pending |
| 23-02-* | compat/store | 1 | D-13–D-22 | T23-01, T23-03, T23-04, T23-06 | Cockpit shape/identity/unknown round-trip；加密、权限、原子写、legacy migration | Python unit | `python3 -m pytest plugins/providers/builtin/codex/tests/test_account_compat.py plugins/providers/builtin/codex/tests/test_account_model.py plugins/providers/builtin/codex/tests/test_account_store.py -q` | ❌ W0 | ⬜ pending |
| 23-03-* | OAuth/apply/export | 2 | D-09–D-12, D-16, D-19, D-23–D-27 | T23-01, T23-02, T23-04, T23-06 | import 不 apply；PKCE/state；apply 仅写 target auth；失败回滚；无进程副作用 | Python protocol/transaction | `python3 -m pytest plugins/providers/builtin/codex/tests/test_oauth.py plugins/providers/builtin/codex/tests/test_apply.py -q` | ❌ W0 | ⬜ pending |
| 23-04-* | account UI | 2 | D-03–D-08, D-15–D-17, D-33–D-37 | T23-01, T23-05 | 四 tab、选择/批量导出、Import/Apply 状态分离、secret-free DTO | Node source/UI contract + typecheck | `cd mac-app && node --test tests/accountFeatureCodex.test.mjs && ./node_modules/.bin/tsc --noEmit` | ❌ W0 | ⬜ pending |
| 23-05-* | session assets | 3 | D-28–D-32 | T23-03, T23-04, T23-06 | 当前 home 限定；30d 边界；ZIP 完整性/冲突；trash/restore 可逆；repair rollback | Python file/archive | `python3 -m pytest plugins/providers/builtin/codex/tests/test_session_assets.py -q` | ❌ W0 | ⬜ pending |
| 23-06-* | integration/regression | 4 | D-01–D-40 | T23-01–T23-06 | 断网/runtime stopped 仍可用；无真实 home；无中转/配额/跨实例功能 | Full source regression | `python3 -m pytest plugins/providers/builtin/codex/tests && cargo test --manifest-path mac-app/src-tauri/Cargo.toml account_feature --lib && cd mac-app && node --test tests/accountFeature*.test.mjs && ./node_modules/.bin/tsc --noEmit && pnpm build` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

表中 plan/task id 是规划前映射；PLAN.md 定稿后只更新编号与命令归属，不得降低 D-01–D-40 和 T23-01–T23-06 覆盖。

## Wave 0 Requirements

- [ ] `plugins/providers/builtin/codex/tests/conftest.py` — synthetic credentials、explicit `plugin_data_dir`、effective-home/tempdir guard，在测试末断言真实 home 未被触碰。
- [ ] `plugins/providers/builtin/codex/tests/test_account_compat.py` — Cockpit commit-pinned object/array/token/agent/API-key/unknown-field fixtures。
- [ ] `plugins/providers/builtin/codex/tests/test_account_model.py` — identity normalization、dedupe/upsert、redacted DTO。
- [ ] `plugins/providers/builtin/codex/tests/test_account_store.py` — AES-GCM vector/round-trip/tamper、0600、atomic/backup/migration/concurrency。
- [ ] `plugins/providers/builtin/codex/tests/test_oauth.py` — fake browser/loopback/clock，PKCE/state/manual callback/cancel/expiry。
- [ ] `plugins/providers/builtin/codex/tests/test_apply.py` — import/apply separation、effective home、byte-for-byte rollback、no-process-side-effects。
- [ ] `plugins/providers/builtin/codex/tests/test_session_assets.py` — synthetic rollout/index/ZIP/trash/repair fixtures。
- [ ] `mac-app/src-tauri` account-feature tests — manifest discovery、opaque action、timeout/error redaction、system capability cancel。
- [ ] `mac-app/tests/accountFeatureHost.test.mjs` 与 `accountFeatureCodex.test.mjs` — sidebar/selector/plugin isolation/UI state/secret-free contract。

复用现有 pytest、Rust 和 Node test 基础设施；不新增测试框架。AES-256-GCM 原语依赖是实现前必须明确批准的产品依赖变更，不得以测试 helper 替代生产实现。

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| system browser OAuth 与 loopback/manual callback UX | D-09–D-10, D-33–D-37 | 真实浏览器、焦点恢复和 macOS callback 需要安装态，且会涉及真实账号 | 仅在用户当前对话明确授权 build/package/install/launch 与测试账号后执行；验证四 tab、browser open、callback/fallback、Escape/focus restore |
| light/dark/system、窄屏和 keyboard 视觉验证 | D-03–D-08, D-33–D-37 | 视觉层级、focus ring、换行和 native dialog 无法完全由 source contract 证明 | 获得明确安装态验证授权后，按 `23-UI-SPEC.md` Acceptance State Matrix 逐项核对 |
| native file/save dialog cancel 与目标权限 | D-16, D-28–D-30 | macOS picker/save dialog 的真实行为需要安装态 | 仅在获授权的临时目录内导入/导出 synthetic fixture；取消不显示错误，不读写真实 home |

## Validation Sign-Off

- [x] 所有规划能力都有自动验证层或 Wave 0 依赖
- [x] Sampling continuity：不存在连续 3 个任务没有自动验证
- [x] Wave 0 覆盖全部当前 MISSING 测试文件
- [x] 不使用 watch-mode flags
- [x] 定向反馈延迟目标低于 30 秒，全量目标低于 120 秒
- [x] `nyquist_compliant: true` 已设置；`wave_0_complete` 待实现测试文件后更新

**Approval:** approved 2026-08-17; installed-app/manual items pending explicit permission

