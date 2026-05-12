# Phase 2: Provider Usage Explorer - Context

**Gathered:** 2026-05-12
**Status:** Executed

<domain>
## Phase Boundary

为桌面工作台新增一个一级 `Usage` 页面，用来查看本地 provider 的每日 token 用量，并在同一页面里切换 `Codex / Claude`。这次范围只覆盖“Usage 作为主导航页面 + provider 侧本地聚合 + 前端展示”，不扩展到 dashboard 摘要、成本筛选、时间范围筛选或新的 provider family。

</domain>

<decisions>
## Implementation Decisions

### Usage page shape
- **D-01:** `Usage` 是一级主导航 tab，而不是 sidebar 小摘要。
- **D-02:** `Usage` 页面参考 `SessionBrowser` 的工作台页面结构，而不是新做一套营销式布局。
- **D-03:** 顶部提供 `Codex / Claude` 切换，第一版只覆盖这两个 builtin providers。

### Provider boundary
- **D-04:** provider-specific usage parsing 保持在 Tauri/Rust provider 命令层，不把解析逻辑写进 React。
- **D-05:** React 只消费统一 `ProviderUsageSummary` contract。
- **D-06:** 这轮按 public repo 内已有 builtin providers 做实现，不突破当前 provider/plugin 边界。

### Data interpretation
- **D-07:** `Codex` 使用本地 `~/.codex/sessions/**/*.jsonl` 的 `token_count` 事件做按日聚合。
- **D-08:** `Claude` 使用本地 `~/.claude/projects/**/*.jsonl` 中的 `message.usage` 做按日聚合。
- **D-09:** `Claude` 需要去重，避免同一 `message.id + requestId` 重复计费。

### the agent's Discretion
- `Usage` 页面内部的具体信息密度和表格布局
- unsupported / empty / error 的文案细节
- 是否展示成本列，以及成本为空时的表现

</decisions>

<specifics>
## Specific Ideas

- 用户明确要求：
  - 新增一个菜单栏，名字是“用量 / Usage”
  - 页面参考 `SessionBrowser`
  - 提供 `Codex / Claude` 切换
  - 接入方式要遵守 plugin/provider 边界
  - 参考 `ryoppippi/ccusage` 的实现思路，不要自行发散

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Product and phase definition
- `.planning/PROJECT.md`
- `.planning/REQUIREMENTS.md`
- `.planning/ROADMAP.md`
- `.planning/STATE.md`

### Existing implementation surfaces
- `mac-app/src/App.tsx`
- `mac-app/src/pages/SessionBrowser.tsx`
- `mac-app/src/components/session-browser/api.ts`
- `mac-app/src/components/session-browser/presentation.tsx`
- `mac-app/src/utils/appTabs.js`
- `mac-app/src/utils/appTabs.d.ts`

### Provider-side integration
- `mac-app/src-tauri/src/commands/provider_sessions.rs`
- `mac-app/src-tauri/src/commands/config.rs`
- `mac-app/src-tauri/src/commands/claude.rs`
- `mac-app/src-tauri/src/lib.rs`

### Validation surface
- `mac-app/tests/appTabs.test.mjs`
- `mac-app/tests/appShell.test.mjs`
- `mac-app/tests/usageBrowser.test.mjs`
- `mac-app/package.json`

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `SessionBrowser` 已经提供了适合工作台的页面节奏、panel 和 fallback 展示模式，可直接复用表达方式。
- `getProviderUi` 与 `StatePanel` 已存在于 session presentation 层，适合继续用于 Usage 页面。
- `PRIMARY_APP_TABS` 已经是主导航单一来源，新增 `usage` 只需要沿用同一模式。

### Established Patterns
- 共享 UI 通过 Tauri `invoke(...)` 读取 Rust 命令层数据。
- provider-specific 能力已经在 Rust 命令层按 runtime/provider 分发，而不是让前端自己识别 provider 内部格式。
- Node 原生测试主要通过静态源码断言验证页面 wiring；Rust 命令逻辑则用内联测试验证聚合行为。

### Integration Points
- `Usage` 页会影响 `App.tsx` 顶层 tab 路由
- `ProviderUsageSummary` 需要新增到共享前端类型
- 新命令 `get_provider_usage_summary` 需要挂到 Tauri invoke handler

</code_context>

<deferred>
## Deferred Ideas

- 更多 provider beyond `codex` / `claude`
- 时间范围选择器、周/月聚合
- 更精细的成本拆解或模型级 breakdown
- dashboard/sidebar 中的 usage 摘要

</deferred>

---

*Phase: 02-provider-usage-explorer*
*Context gathered: 2026-05-12*
