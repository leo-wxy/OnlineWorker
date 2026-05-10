# Phase 1: UI Foundation - Context

**Gathered:** 2026-05-10
**Status:** Ready for planning

<domain>
## Phase Boundary

为桌面工作台建立稳定的共享视觉和布局基线，优先收敛最常用的应用壳层与导航结构，让 `Dashboard`、`Setup`、`Sessions`、`Commands` 在切换时不再像彼此独立的页面。当前这次讨论收敛到应用壳层本身，不扩展到新功能或新页面。

</domain>

<decisions>
## Implementation Decisions

### Sidebar behavior
- **D-01:** 左侧导航栏需要支持收缩 / 展开两种状态。
- **D-02:** 收缩后保留窄栏，不做整栏隐藏。
- **D-03:** 收缩态以导航图标为主，优先保持日常切换效率，而不是完全极简到不可识别。

### Sidebar scope
- **D-04:** 这一轮先处理应用壳层和导航交互，不扩展到底层 provider、session 内容区或新的设置能力。
- **D-05:** 收缩态可以隐藏低频辅助块，例如语言切换和底部状态摘要，只保留核心导航可达性。

### Window chrome cleanup
- **D-06:** 左上角当前的虚线框应移除。
- **D-07:** 去掉虚线框时仍需保留必要的窗口拖拽能力，不能破坏 Tauri 标题栏拖拽体验。

### the agent's Discretion
- 收缩按钮的具体图标、位置和文案处理
- 收缩态宽度的具体数值
- 收缩态下品牌卡片、工具提示和 hover 反馈的具体实现
- 是否将收缩状态只保存在前端内存中，或顺手抽成后续可持久化的局部状态

</decisions>

<specifics>
## Specific Ideas

- 当前用户明确指出的两个可见问题：
  - 左侧菜单栏需要支持收缩 / 展开切换
  - 左上角存在一个“不知道什么玩意”的虚线框，需要去掉
- 用户明确接受的交互方向：
  - 收缩后保持窄栏，不做完全隐藏

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Product scope and phase definition
- `.planning/PROJECT.md` — 项目定位、当前里程碑边界、非目标范围
- `.planning/REQUIREMENTS.md` — `UI-01` / `UI-02` 的正式要求
- `.planning/ROADMAP.md` — Phase 1 的目标、成功标准和计划拆分
- `.planning/STATE.md` — 当前阶段状态和延续约束

### Existing implementation
- `mac-app/src/App.tsx` — 当前应用壳层、侧栏、顶层 tab 导航和拖拽区域实现
- `mac-app/src/index.css` — 当前壳层视觉基线、sidebar 样式、drag strip 样式
- `mac-app/src/utils/appTabs.js` — 主导航 tab 定义来源
- `mac-app/src/i18n/locales/en.ts` — 现有导航和界面文案
- `mac-app/src/i18n/locales/zh.ts` — 中文导航和界面文案

### Validation surface
- `mac-app/package.json` — 前端 build/test 入口
- `mac-app/tests/sessionMetadataBadges.test.mjs` — 现有 Node 原生测试风格样例
- `README.md` — 对外产品定位，约束 UI 不要偏离“本地工作台”产品形态

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `App.tsx` 已集中承载应用壳层、左侧导航、顶部拖拽区域和主内容切换；这次改动优先在这里收口，不需要拆新页面。
- `PRIMARY_APP_TABS` 和 `t.app.tabs[...]` 已经提供稳定的导航定义与多语言标题，可直接复用到收缩态导航。
- `handleWindowDrag` 已封装窗口拖拽行为，可继续复用到更干净的拖拽热区。

### Established Patterns
- 当前 UI 使用 React 18 + Tailwind + 少量全局 CSS token 组合；壳层样式既有 Tailwind utility，也有 `ow-*` 全局类。
- sidebar 目前固定宽度 `248px`，导航项是图标 + 标签按钮，激活态通过 `ow-tab-button-active::before` 左侧高亮条表达。
- 当前顶层拖拽区域包含一个独立的 `ow-drag-strip`，虚线框问题就来自这里。

### Integration Points
- Phase 1 的应用壳层调整将直接影响 `Dashboard` / `Setup` / `Sessions` / `Commands` 的切换体验，但不需要修改这些页面的业务逻辑。
- 若收缩态隐藏部分辅助块，需要确保 i18n 仍完整存在，不要通过删文案来实现“隐藏”。
- 任何视觉改动都要和 Tauri `hiddenTitle` + `titleBarStyle: "Overlay"` 的窗口行为兼容。

</code_context>

<deferred>
## Deferred Ideas

- Sidebar 收缩状态持久化到本地存储或用户配置
- 针对 `Dashboard`、`Setup`、`Sessions`、`Commands` 的页面内组件重排
- 更大范围的配色、卡片、阴影和页面密度整体重构

</deferred>

---

*Phase: 01-ui-foundation*
*Context gathered: 2026-05-10*
