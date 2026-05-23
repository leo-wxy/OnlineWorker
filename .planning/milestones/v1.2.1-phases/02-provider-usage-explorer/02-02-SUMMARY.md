---
phase: 02-provider-usage-explorer
plan: 02
subsystem: usage-ui
tags: [react, tauri, navigation, usage-page, i18n]
requires:
  - 02-01
provides:
  - 一级 Usage 主导航
  - Codex / Claude 页面内切换
  - Usage fallback 状态、近 7 天筛选、汇总卡、柱状图与 daily table
affects: [app-shell, navigation, desktop-usage-page]
tech-stack:
  added: []
  patterns: [first-class-nav-tab, provider-switcher, shared-state-panel, date-window-query, installed-app-validation]
key-files:
  created:
    - mac-app/src/pages/UsageBrowser.tsx
    - mac-app/tests/usageBrowser.test.mjs
  modified:
    - mac-app/src/App.tsx
    - mac-app/src/pages/index.ts
    - mac-app/src/utils/appTabs.js
    - mac-app/src/utils/appTabs.d.ts
    - mac-app/src/i18n/types.ts
    - mac-app/src/i18n/locales/en.ts
    - mac-app/src/i18n/locales/zh.ts
    - mac-app/tests/appTabs.test.mjs
    - mac-app/tests/appShell.test.mjs
requirements-completed: [USG-01, USG-02]
completed: 2026-05-12
---

# Phase 2 Plan 02 Summary

## Accomplishments

- `Usage` 已加入主导航一级 tab，并接入 `App.tsx` 顶层页面路由
- 新增 `UsageBrowser` 页面，提供 `Codex / Claude` 切换与刷新
- 页面复用了现有工作台表达方式，包括 `StatePanel` 和 provider UI helper
- 中英文 i18n 和 app tab 类型已同步补齐
- `Usage` 页面默认按近 7 天加载，并支持开始/结束日期筛选
- 页面补充了 loading / applying 态，避免切 provider 或改时间范围时误以为卡死
- 页面从基础 daily table 扩展为汇总卡 + 柱状图 + 明细表的三层结构
- 安装态 `OnlineWorker.app` 已完成重新打包、覆盖安装和启动验证

## Key Decisions

- `Usage` 做成完整页面，而不是 sidebar 小摘要
- 页面结构参考 `SessionBrowser` 的工作台风格，而不是新建营销式布局
- 错误、空态、unsupported 状态用统一 fallback panel 表达
- 默认查询窗口固定为近 7 天，避免首次进入页面全量扫描历史 provider 数据
- 图表和筛选只消费统一 summary contract；provider-specific 时间范围读取仍留在 Rust 命令层
- Telegram 最终回复富文本渲染修正已纳入安装态验证闭环，避免 Phase 2 交付时留下明显体验裂缝

## Verification

- `node --test mac-app/tests/appShell.test.mjs mac-app/tests/appTabs.test.mjs mac-app/tests/usageBrowser.test.mjs`
- `node --test mac-app/tests/*.test.mjs`
- `cd mac-app && npm run build`
- `bash scripts/build.sh`
- 安装态 `/Applications/OnlineWorker.app` 覆盖安装后启动成功，运行二进制与最新 `target/release/onlineworker-app` 一致（`cmp_exit=0`）

## Known Limits

- 当前仍只覆盖 `codex / claude`
- 当前只做按日窗口展示，不提供周/月切换或模型级 breakdown

---
*Completed: 2026-05-12*
