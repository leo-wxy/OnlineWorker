---
phase: 22
slug: dark-mode-support
status: source-complete
nyquist_compliant: true
wave_0_complete: true
created: 2026-08-15
---

# Phase 22 — Validation Strategy

> Phase 22 的反馈采样契约。源级与构建检查可在开发阶段运行；打包、安装、覆盖和重启 OnlineWorker.app 必须在当前对话另获用户明确许可。

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Node.js built-in `node:test` + TypeScript compiler + Vite build |
| **Config file** | `mac-app/package.json`；Node source-contract tests 无独立配置 |
| **Quick run command** | `cd mac-app && node --test tests/theme.test.mjs tests/themeContract.test.mjs tests/appShell.test.mjs tests/menubarPopover.test.mjs` |
| **Full suite command** | `cd mac-app && node --test tests/*.test.mjs && ./node_modules/.bin/tsc --noEmit && pnpm build` |
| **Estimated runtime** | quick ~10s；full ~60s（以本机实测为准） |

---

## Sampling Rate

- **After every task commit:** 运行覆盖本任务的最小 `node --test` 文件；涉及主题运行时、App shell 或 menubar 时运行完整 quick command。
- **After every plan wave:** 运行 full suite command，并执行 `git diff --check`。
- **Before `$gsd-verify-work`:** full suite 必须为 green；源级硬编码扫描必须逐项解释或清零。
- **Max feedback latency:** 目标 60 秒；若全量构建更慢，任务内先跑定向 Node test，再在 wave 结束运行全量。

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 22-01-01 | 01 | 1 | D-01, D-02, D-10, D-11 | — | 非法/缺失偏好安全回退到 System | unit/source contract | `cd mac-app && node --test tests/theme.test.mjs` | ✅ | ✅ green |
| 22-01-02 | 01 | 1 | D-10 | — | 仅在用户确认后增加最小 window theme 权限 | confirmation checkpoint | `N/A — manual approval gate` | ✅ | ✅ green |
| 22-01-03 | 01 | 1 | D-01, D-02, D-10, D-11 | — | 主题运行时失败不阻塞业务 | unit/source contract | `cd mac-app && node --test tests/theme.test.mjs tests/appShell.test.mjs tests/bundleSplitting.test.mjs && ./node_modules/.bin/tsc --noEmit` | ✅ | ✅ green |
| 22-02-01 | 02 | 1 | D-07, D-12, D-13, D-14 | — | 文档与 CSS token 由同一可运行契约约束 | token/docs contract | `cd mac-app && node --test tests/themeContract.test.mjs` | ✅ | ✅ green |
| 22-02-02 | 02 | 1 | D-05, D-06, D-07, D-12, D-13 | — | N/A | token/docs contract + typecheck | `cd mac-app && node --test tests/themeContract.test.mjs && ./node_modules/.bin/tsc --noEmit` | ✅ | ✅ green |
| 22-02-03 | 02 | 1 | D-13, D-14 | — | 规范只从稳定文档入口引用，不复制 token | docs contract | `cd mac-app && node --test tests/themeContract.test.mjs` | ✅ | ✅ green |
| 22-03-01 | 03 | 2 | D-03, D-04, D-06, D-08, D-10 | — | 透明 menubar 外壳不接受第二套偏好 writer | App/menubar contract | `cd mac-app && node --test tests/appShell.test.mjs tests/menubarPopover.test.mjs tests/theme.test.mjs` | ✅ | ✅ green |
| 22-03-02 | 03 | 2 | D-01, D-03, D-04, D-06, D-09, D-12, D-13 | — | N/A | App shell contract + typecheck | `cd mac-app && node --test tests/appShell.test.mjs tests/theme.test.mjs && ./node_modules/.bin/tsc --noEmit` | ✅ | ✅ green |
| 22-03-03 | 03 | 2 | D-05, D-06, D-08, D-09, D-10, D-13 | — | menubar 只消费共享主题，外壳保持透明 | menubar contract + typecheck | `cd mac-app && node --test tests/menubarPopover.test.mjs tests/theme.test.mjs && ./node_modules/.bin/tsc --noEmit` | ✅ | ✅ green |
| 22-04-01..03 | 04 | 3 | D-05, D-06, D-07, D-09, D-13 | — | N/A | source contract + typecheck | `cd mac-app && node --test tests/taskBoard.test.mjs tests/dashboardProviderStatus.test.mjs && ./node_modules/.bin/tsc --noEmit` | ✅ | ✅ green |
| 22-05-01..03 | 05 | 3 | D-05, D-06, D-07, D-09, D-13 | — | N/A | source contract + typecheck | `cd mac-app && node --test tests/usageBrowser.test.mjs tests/commandRegistryView.test.mjs tests/sessionArchiveContextMenu.test.mjs tests/sessionBrowserState.test.mjs tests/sessionComposerAttachments.test.mjs tests/sessionMarkdown.test.mjs && ./node_modules/.bin/tsc --noEmit` | ✅ | ✅ green |
| 22-06-01..02 | 06 | 3 | D-05, D-06, D-07, D-09, D-12, D-13, D-14 | — | N/A | source contract + typecheck | `cd mac-app && node --test tests/configEditorCopy.test.mjs tests/settingsProviders.test.mjs tests/supportBundleMaintenance.test.mjs tests/themeContract.test.mjs && ./node_modules/.bin/tsc --noEmit` | ✅ | ✅ green |
| 22-06-03 | 06 | 3 | D-06, D-07, D-09, D-12, D-13, D-14 | — | 未解释主题硬编码为零，安装态不越权执行 | full regression | `cd mac-app && node --test tests/*.test.mjs && ./node_modules/.bin/tsc --noEmit && pnpm build` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

任务编号已与最终 PLAN.md 对齐；后续若调整拆分，只允许更新编号和命令归属，不得降低 D-01–D-14 的覆盖。

---

## Wave 0 Requirements

- [x] `mac-app/tests/theme.test.mjs` — 偏好校验、System 解析、首帧 bootstrap、Tauri/window 与跨窗口事件同步契约。
- [x] `mac-app/tests/themeContract.test.mjs` — light/dark token、旧 alias、`docs/UI-THEME.md` 和禁止硬编码规则的契约。
- [x] 扩展 `mac-app/tests/appShell.test.mjs` — 选择器位置、侧栏折叠隐藏和 React 首帧前初始化。
- [x] 扩展 `mac-app/tests/menubarPopover.test.mjs` — 透明外壳、既有信息结构和共享主题同步。

现有 Node/TypeScript/Vite 基础设施足够，不安装测试框架或主题依赖。

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 选定的深蓝灰玻璃暗色与冷白/雾蓝浅色保持和谐 | D-05, D-07 | 色调、材质层级和视觉和谐无法由 source contract 判断 | 对照现有 Dashboard 布局，在 Light/Dark 下检查背景、表面、文字、边框、语义色和阴影；不得改变卡片尺寸或信息结构 |
| 所有页面和交互状态完整覆盖 | D-06, D-09 | hover/focus/selected/disabled/loading/error 与真实内容组合需要人工观察 | 遍历 Dashboard、Task Board、Sessions、Usage、Commands、Setup、全部 Settings、Config、弹窗、菜单、表单与滚动条，检查 Light/Dark/System |
| 主窗口与 menubar 即时一致 | D-08, D-10 | 两个独立 WKWebView 与透明原生窗口的实时表现不能仅靠静态测试证明 | 保持主窗口和 menubar 打开，分别切换三档主题及 macOS 外观；确认两处立即同步且 menubar 外壳无白边/黑块 |
| 首帧无亮色闪屏且偏好跨重启持久化 | D-01, D-11 | 必须观察真实应用冷启动/重启 | 在获准的安装态验证中分别以 System/Light/Dark 冷启动，确认首帧即为目标主题并在重启后保留选择 |
| 约 150ms 主题过渡与 reduced-motion | D-12 | 动画时长和整体感受需要视觉检查 | 手动切换主题，确认只过渡颜色/背景/边框/阴影；启用减少动态效果后确认过渡关闭或显著缩短，无整窗淡入淡出 |
| 原生窗口主题与 app 内容一致 | D-02, D-10 | capability 与 macOS 原生窗口行为只有安装态是运行真相 | 获得明确许可后运行仓库规定的 packaged-app 验证链，检查 native chrome、主窗口、menubar 和系统外观联动 |

---

## Validation Sign-Off

- [x] 所有最终任务都有 `<automated>` verify 或 Wave 0 依赖
- [x] Sampling continuity：不存在连续 3 个任务没有自动验证
- [x] Wave 0 覆盖所有 MISSING 测试文件与现有契约扩展
- [x] 不使用 watch-mode flags
- [x] quick feedback latency 实测低于 60 秒
- [x] `nyquist_compliant: true` 已在 PLAN.md 定稿后设置

**Approval:** source checks passed; installed-app manual verification pending explicit permission
