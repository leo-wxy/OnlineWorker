---
phase: 23-plugin-owned-codex-account-and-session-asset-management
plan: 12
subsystem: account-feature
tags: [codex, account, quota, session-assets, plugin]

requires:
  - phase: 23-02..23-11
    provides: generic host, plugin-owned Codex account/session implementation and UI
provides:
  - phase-wide security and forbidden-coupling regression guards
  - official manual quota refresh and explicit reapply coverage
  - cwd/project-grouped conversation asset UI
  - combined package and mounted-DMG visual evidence
affects: [phase-23-closure]

tech-stack:
  added: []
  patterns: [plugin-owned frontend CSS, independent resident account worker, versioned redacted summary cache, explicit network action, deferred local usage scan]

key-files:
  created:
    - plugins/providers/builtin/codex/python/quota.py
    - plugins/providers/builtin/codex/tests/test_quota.py
    - plugins/providers/builtin/codex/frontend/account.css
    - plugins/providers/builtin/codex/frontend/accountSummaryStorage.ts
  modified:
    - main.py
    - tests/test_account_features.py
    - mac-app/src-tauri/src/commands/account_feature.rs
    - mac-app/src-tauri/src/lib.rs
    - plugins/providers/builtin/codex/python/account_feature.py
    - plugins/providers/builtin/codex/python/apply.py
    - plugins/providers/builtin/codex/python/session_assets.py
    - plugins/providers/builtin/codex/frontend/AccountOverview.tsx
    - plugins/providers/builtin/codex/frontend/SessionAssetsPage.tsx
    - plugins/providers/builtin/codex/tests/test_phase23_boundaries.py
    - mac-app/tests/accountFeatureCodex.test.mjs
    - mac-app/tests/accountFeatureRegression.test.mjs

key-decisions:
  - "Only explicit user-triggered quota refresh calls the fixed official Codex usage endpoint; account listing performs no background network request."
  - "Session storage remains conversation-based, while the UI groups conversations by cwd/project and defaults groups to collapsed."
  - "Plugin-owned CSS fixes packaged layout without expanding the host Tailwind scan or adding a dependency."
  - "Account discovery/actions share one independent early JSONL worker; it has no provider bridge/app-server authority, clears on timeout/crash, and never auto-replays a failed action."
  - "Account cards may initialize from a versioned allowlist of redacted display fields, then authoritative accounts.list replaces the cache in the background."

requirements-completed: [D-01, D-02, D-03, D-04, D-05, D-06, D-07, D-08, D-09, D-10, D-11, D-12, D-13, D-14, D-15, D-16, D-17, D-18, D-19, D-20, D-21, D-22, D-23, D-24, D-25, D-26, D-27, D-28, D-29, D-30, D-31, D-32, D-33, D-34, D-35, D-36, D-37, D-38, D-39, D-40]

completed: 2026-08-18
---

# Phase 23 Plan 12: 安全边界、回归与打包验证 Summary

**Phase 23 的插件独立边界、账号/额度/会话资产主流程、源码回归和 mounted-DMG UI 均已收口。**

## Accomplishments

- Codex 插件当前独立提供 OAuth 与 Token / JSON 账号新增、Cockpit 兼容导出、显式 apply/reapply、官方额度刷新和安全存储；专属 API Key / 本地文件新增动作已在后续范围收缩中移除，host 仍不含 Codex 业务分支。
- 会话后端按 conversation 处理本地资产，前端按 `cwd`/project 默认折叠分组，展开后显示各 conversation。
- source guards 固定 OAuth/usage endpoint、trusted handles、真实目录拒绝、shared lock 和 live runtime 零耦合边界。
- combined wrapper 生成 `OnlineWorker_1.9.0_aarch64.dmg`；挂载运行后完成账号页、添加弹窗和会话分组的只读视觉验证。
- 2026-08-18 performance follow-up 消除了每次账号 action 的 Python sidecar 冷启动，并让脱敏账号摘要先显示、后台校准；账号业务仍完全留在插件，未接 provider/app-server。
- performance follow-up 的 combined build/install verification 通过；安装版 cache-hit 账号行在 449 ms 内显示，常驻 worker process tree 保持稳定。会话刷新仍需 6.0 s，未被本次账号链路优化覆盖。

## Deviations from Original Plan

- 用户在实现阶段将“显式额度刷新”加入范围，因此 D-38 从“完全排除 quota”修订为“仅允许显式官方 usage 读取，继续排除后台轮询与账号池”。
- 参考 Cockpit 的实际信息结构后，会话一级列表由 conversation 平铺改为 `cwd`/project 分组，conversation 保持二级资产单位。
- 用户后续明确授权打包验证；初次执行 combined build 和 mounted-DMG 只读 QA，performance follow-up 再执行 `verify-packaged-fast.sh` 并安装到 `/Applications` 验证。
- 用户后续将账号新增入口收缩为 OAuth 与 Token / JSON，并要求账号行共享固定列轨；历史 API-key/文件来源记录继续兼容展示和导出。

## Verification

- `python3 -m pytest tests/test_account_features.py tests/test_packaging_socks_support.py plugins/providers/builtin/codex/tests -q` — 51 passed。
- `cargo test --manifest-path mac-app/src-tauri/Cargo.toml account_feature --lib` — 11 passed。
- `cd mac-app && node --test tests/accountFeature*.test.mjs` — 5 passed。
- `cd mac-app && ./node_modules/.bin/tsc --noEmit` — passed。
- `bash build.sh`（combined shell）— passed；39 MB DMG 已生成并从挂载卷启动，SHA-256 `b3bd54ab4485160268f285e8fba4474ac9f19b63f2f57c111dc6c3360035193c`。
- 范围收缩前的 Mounted-DMG UI 历史证据 — 当时的账号入口/四源弹窗/额度入口/reapply 可见；会话页显示 31 个 project groups 和 71 条 conversations。当前双入口与固定列轨 follow-up 需以本轮源码/视觉验证为准。
- Performance follow-up source verification：Python account/Codex regression 47 passed；Rust account feature 10 passed；account feature Node contracts 10 passed；`npm run build` passed。
- Performance follow-up packaged verification：`verify-packaged-fast.sh` 113 s passed；39 MB DMG SHA-256 `6c1a6b0ae4b40e41196fe1897a4074f930e12f5d2e2a1e96120e75e0e8a38472`；安装版账号 cache-hit 449 ms，resident worker tree 稳定；会话刷新 6001 ms。
- OAuth/Token-only 与固定列轨 follow-up：Python account/Codex regression `44 passed`；Node account contracts `10 passed`；TypeScript 与 `pnpm build` passed；1440px Light/Dark 及 900px Light 截图确认身份状态、额度和操作列对齐且无横向溢出。

## Not Executed

- 未主动对用户真实账号执行 OAuth、apply/reapply、账号导入导出。
- 未执行会话导入导出、trash/restore/visibility repair。
- 已安装并启动 `/Applications/OnlineWorker.app`；未验证上述 credential/session mutation action 的安装包时延。
- 会话完整刷新实测 6.0 s，仍需单独优化，不声明为本 follow-up 已修复。
- 当前 OAuth/Token-only 与固定列轨 follow-up 未执行打包、安装或真实账号 mutation；浏览器截图不是 installed-app 验证。
- 本阶段没有创建 commit 或 push。

## Self-Check

PASS

---
*Phase: 23-plugin-owned-codex-account-and-session-asset-management*
*Completed: 2026-08-18*
