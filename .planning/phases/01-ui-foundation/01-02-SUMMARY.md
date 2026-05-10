---
phase: 01-ui-foundation
plan: 02
subsystem: ui
tags: [react, tauri, drag-region, css, shell-polish]
requires: []
provides:
  - 左上角虚线 drag strip 清理
  - sidebar/品牌区更稳定的壳层基线
  - 品牌卡片高度稳定化，减少菜单区域随形态切换抖动
affects: [desktop-shell, visual-baseline, window-dragging]
tech-stack:
  added: []
  patterns: [stable-shell-height, drag-region-visual-separation, narrow-rail-polish]
key-files:
  created: []
  modified: [mac-app/src/App.tsx, mac-app/src/index.css, mac-app/tests/appShell.test.mjs]
key-decisions:
  - "去掉 drag strip 的虚线视觉，但保留 Tauri 拖拽热区和 startDragging 逻辑"
  - "品牌卡片高度固定，避免展开/收缩时把菜单整体顶动"
patterns-established:
  - "Pattern: 桌面壳层热区与可见视觉要解耦，避免为了提示拖拽而制造噪音"
  - "Pattern: 壳层切换优先保持容器高度稳定，只让必要的外层宽度变化"
requirements-completed: [UI-01, UI-02]
duration: 42min
completed: 2026-05-10
---

# Phase 1: UI Foundation Summary

**应用壳层移除了左上角虚线拖拽框，并把品牌区与菜单起始位置稳定下来，减少侧栏切换时的视觉抖动**

## Performance

- **Duration:** 42 min
- **Started:** 2026-05-10T22:32:00+08:00
- **Completed:** 2026-05-10T23:14:24+08:00
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments
- 去掉了左上角显眼的虚线 drag strip 视觉，同时保留现有 Tauri 窗口拖拽链路
- 补齐了 sidebar 收缩态所需的共享样式，并收敛了按钮和品牌区的壳层视觉
- 通过固定品牌卡片高度，解决了侧栏展开/收缩时菜单起始位置跟着跳动的主要来源

## Task Commits

本轮未做原子 git commit；当前仍处于工作区内联开发阶段。

## Files Created/Modified
- `mac-app/src/App.tsx` - 清理 drag 区视觉、收敛 sidebar 控制项布局、稳定品牌卡片高度
- `mac-app/src/index.css` - 删除 `ow-drag-strip` 虚线视觉并补最小 sidebar toggle 样式
- `mac-app/tests/appShell.test.mjs` - 为壳层结构和稳定高度补最小静态测试约束

## Decisions Made
- drag strip 的问题是视觉问题，不是热区问题，所以采取“保留拖拽能力、去掉虚线提示”的处理
- 菜单栏抖动的主因被收敛到品牌卡片高度不一致，因此通过固定品牌卡片高度和保持布局结构稳定来修正

## Deviations from Plan

计划中原本只要求清理 drag strip 和补共享样式；执行中根据真实交互反馈，额外收敛了品牌卡片高度和 sidebar 切换抖动来源。这仍属于壳层 polish 范围，没有超出 Phase 1 的 UI baseline 目标。

## Issues Encountered
- 静态 HTML 预览无法代表真实效果，因为前端顶层依赖 Tauri runtime；验证入口必须切回 `tauri dev` 或安装态 app
- “抖动”最初看起来像 sidebar 宽度动画问题，实际根因是品牌卡片在不同形态下高度不一致，导致下面菜单整体位移

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- 应用壳层已经具备继续打磨 `Setup` 信息层级的稳定基线
- 当前阶段的源码态验证完成，但安装态 `OnlineWorker.app` 的最终交互手感仍待补验

---
*Phase: 01-ui-foundation*
*Completed: 2026-05-10*
