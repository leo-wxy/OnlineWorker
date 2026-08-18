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
  patterns: [plugin-owned frontend CSS, explicit network action, deferred local usage scan]

key-files:
  created:
    - plugins/providers/builtin/codex/python/quota.py
    - plugins/providers/builtin/codex/tests/test_quota.py
    - plugins/providers/builtin/codex/frontend/account.css
  modified:
    - plugins/providers/builtin/codex/python/account_feature.py
    - plugins/providers/builtin/codex/python/apply.py
    - plugins/providers/builtin/codex/python/session_assets.py
    - plugins/providers/builtin/codex/frontend/AccountOverview.tsx
    - plugins/providers/builtin/codex/frontend/SessionAssetsPage.tsx
    - plugins/providers/builtin/codex/tests/test_phase23_boundaries.py
    - mac-app/tests/accountFeatureCodex.test.mjs

key-decisions:
  - "Only explicit user-triggered quota refresh calls the fixed official Codex usage endpoint; account listing performs no background network request."
  - "Session storage remains conversation-based, while the UI groups conversations by cwd/project and defaults groups to collapsed."
  - "Plugin-owned CSS fixes packaged layout without expanding the host Tailwind scan or adding a dependency."

requirements-completed: [D-01, D-02, D-03, D-04, D-05, D-06, D-07, D-08, D-09, D-10, D-11, D-12, D-13, D-14, D-15, D-16, D-17, D-18, D-19, D-20, D-21, D-22, D-23, D-24, D-25, D-26, D-27, D-28, D-29, D-30, D-31, D-32, D-33, D-34, D-35, D-36, D-37, D-38, D-39, D-40]

completed: 2026-08-18
---

# Phase 23 Plan 12: 安全边界、回归与打包验证 Summary

**Phase 23 的插件独立边界、账号/额度/会话资产主流程、源码回归和 mounted-DMG UI 均已收口。**

## Accomplishments

- Codex 插件独立提供四源账号导入、Cockpit 兼容导出、显式 apply/reapply、官方额度刷新和安全存储；host 不含 Codex 业务分支。
- 会话后端按 conversation 处理本地资产，前端按 `cwd`/project 默认折叠分组，展开后显示各 conversation。
- source guards 固定 OAuth/usage endpoint、trusted handles、真实目录拒绝、shared lock 和 live runtime 零耦合边界。
- combined wrapper 生成 `OnlineWorker_1.9.0_aarch64.dmg`；挂载运行后完成账号页、添加弹窗和会话分组的只读视觉验证。

## Deviations from Original Plan

- 用户在实现阶段将“显式额度刷新”加入范围，因此 D-38 从“完全排除 quota”修订为“仅允许显式官方 usage 读取，继续排除后台轮询与账号池”。
- 参考 Cockpit 的实际信息结构后，会话一级列表由 conversation 平铺改为 `cwd`/project 分组，conversation 保持二级资产单位。
- 用户后续明确授权打包验证，因此执行了 combined build 和 mounted-DMG 只读 QA；仍未安装到 `/Applications`。

## Verification

- `python3 -m pytest tests/test_account_features.py tests/test_packaging_socks_support.py plugins/providers/builtin/codex/tests -q` — 51 passed。
- `cargo test --manifest-path mac-app/src-tauri/Cargo.toml account_feature --lib` — 11 passed。
- `cd mac-app && node --test tests/accountFeature*.test.mjs` — 5 passed。
- `cd mac-app && ./node_modules/.bin/tsc --noEmit` — passed。
- `bash build.sh`（combined shell）— passed；39 MB DMG 已生成并从挂载卷启动，SHA-256 `b3bd54ab4485160268f285e8fba4474ac9f19b63f2f57c111dc6c3360035193c`。
- Mounted-DMG UI — 账号入口/账号卡片/四源弹窗/额度入口/reapply 可见；会话页显示 31 个 project groups 和 71 条 conversations，展开行为通过。

## Not Executed

- 未对用户真实账号执行 OAuth、额度网络刷新、apply/reapply、账号导入导出。
- 未执行会话导入导出、trash/restore/visibility repair。
- 未安装或覆盖 `/Applications/OnlineWorker.app`。
- 本阶段没有创建 commit 或 push。

## Self-Check

PASS

---
*Phase: 23-plugin-owned-codex-account-and-session-asset-management*
*Completed: 2026-08-18*
