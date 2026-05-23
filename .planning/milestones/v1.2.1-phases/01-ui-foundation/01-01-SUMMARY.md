---
phase: 01-ui-foundation
plan: 01
subsystem: ui
tags: [react, tauri, sidebar, navigation, desktop-shell]
requires: []
provides:
  - 应用壳层的 sidebar 收缩 / 展开状态
  - 窄栏模式下的主导航可用性
  - 侧栏控制项与导航结构的一致入口
affects: [setup, dashboard, sessions, commands, desktop-shell]
tech-stack:
  added: []
  patterns: [shell-local-ui-state, collapsible-sidebar, icon-first-narrow-rail]
key-files:
  created: []
  modified: [mac-app/src/App.tsx, mac-app/tests/appShell.test.mjs, mac-app/src/i18n/locales/en.ts, mac-app/src/i18n/locales/zh.ts, mac-app/src/i18n/types.ts]
key-decisions:
  - "侧栏收缩状态保留在 App.tsx 本地状态中，不引入全局 store"
  - "收缩后保留窄栏，而不是彻底隐藏 sidebar"
patterns-established:
  - "Pattern: 顶层工作台壳层交互优先收口在 App.tsx，而不是分散进各页面"
  - "Pattern: sidebar 收缩态保留图标导航可达性，降低壳层切换成本"
requirements-completed: [UI-01, UI-02]
duration: 55min
completed: 2026-05-10
---

# Phase 1: UI Foundation Summary

**桌面工作台壳层获得可收缩的左侧导航，并保留窄栏模式下的高频 tab 切换能力**

## Performance

- **Duration:** 55 min
- **Started:** 2026-05-10T22:19:00+08:00
- **Completed:** 2026-05-10T23:14:24+08:00
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments
- 在 `App.tsx` 中为桌面壳层增加了 `sidebarCollapsed` 本地状态和收缩/展开切换入口
- 建立了窄栏模式下仍可用的主导航结构，保证 `Dashboard`、`Setup`、`Sessions`、`Commands` 在收缩态仍可快速切换
- 为这类壳层交互补上了最小 Node 测试覆盖，并同步补齐了中英文 tooltip 文案与 i18n 类型

## Task Commits

本轮未做原子 git commit；当前仍处于工作区内联开发阶段。

## Files Created/Modified
- `mac-app/src/App.tsx` - 新增 sidebar 收缩状态、窄栏导航和壳层交互控制
- `mac-app/tests/appShell.test.mjs` - 新增应用壳层测试，覆盖 sidebar 收缩行为和文案存在性
- `mac-app/src/i18n/locales/en.ts` - 增加 sidebar 收缩/展开文案
- `mac-app/src/i18n/locales/zh.ts` - 增加 sidebar 收缩/展开文案
- `mac-app/src/i18n/types.ts` - 为 `app.sidebar` 增加类型定义

## Decisions Made
- 侧栏收缩状态保持为 `App.tsx` 本地 UI 状态，因为当前交互只影响应用壳层，不值得引入共享状态
- 收缩态保留窄栏和图标导航，而不是整栏隐藏，以保证桌面工作台的高频切换效率

## Deviations from Plan

相对原计划有一处有效偏移：收缩控制项的布局经过多次视觉收敛，最终从品牌卡片内部移到品牌卡片下方，并做成与菜单项同宽的整行控制，以降低“补丁感”。这属于 Phase 1 边界内的 UI 收口，没有扩大范围。

## Issues Encountered
- 直接用普通浏览器打开 `dist/index.html` 会空白，因为 `App.tsx` 顶层依赖 Tauri runtime，不适合作为纯静态网页验证入口
- sidebar 控件位置第一版不直观，后续改成品牌卡片下方的整行控制项后更符合桌面工作台壳层逻辑

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Phase 2 可以直接在现有壳层基础上继续打磨 `Setup` 首屏信息层级和 readiness 表达
- 当前源码态 `tauri dev`、Node 测试、前端 build 已通过
- 仍需注意：安装态 `OnlineWorker.app` 的最终交互验证这轮还未补做

---
*Phase: 01-ui-foundation*
*Completed: 2026-05-10*
