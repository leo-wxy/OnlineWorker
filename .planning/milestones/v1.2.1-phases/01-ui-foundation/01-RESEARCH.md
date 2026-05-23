# Phase 1: UI Foundation - Research

**Researched:** 2026-05-10
**Domain:** React + Tauri desktop shell layout refinement
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- 左侧导航栏需要支持收缩 / 展开两种状态
- 收缩后保留窄栏，不做整栏隐藏
- 收缩态以导航图标为主，优先保持日常切换效率
- 这一轮只处理应用壳层和导航交互，不扩展到新功能
- 左上角当前虚线框应移除
- 去掉虚线框时仍需保留必要的窗口拖拽能力

### the agent's Discretion
- 收缩按钮的具体图标、位置和交互细节
- 收缩态宽度的具体数值
- 收缩态下品牌卡片、工具提示和 hover 反馈的细节
- 收缩状态是否仅保存在内存态

### Deferred Ideas (OUT OF SCOPE)
- 收缩状态持久化
- 页面内容区大规模重排
- 全局视觉系统再设计

</user_constraints>

<architectural_responsibility_map>
## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 应用壳层导航收缩/展开 | Browser/Client | Frontend Server | 纯前端状态与渲染行为，无需 Rust 参与 |
| 左侧导航宽度与文案显隐 | Browser/Client | — | 由 React 组件状态和 CSS 决定 |
| 窗口拖拽热区保留 | Browser/Client | API/Backend | 视觉和热区在前端，但依赖 Tauri window API 触发拖拽 |
| 去掉虚线 drag strip 外观 | Browser/Client | — | 属于前端样式问题 |

</architectural_responsibility_map>

<research_summary>
## Summary

当前仓库的应用壳层集中在 `mac-app/src/App.tsx`，左侧 sidebar、顶部拖拽区域、首屏 banner 和主内容切换都在一个文件里。这意味着 Phase 1 的目标可以用局部壳层改动实现，不需要先拆新的 layout framework，也不需要进入 Rust/Tauri 命令层。

现有实现已经具备三个关键基础：一是导航 tab 数据集中且稳定，二是窗口拖拽已经通过 `data-tauri-drag-region` 和 `startDragging()` 打通，三是全局样式已经有 `ow-sidebar`、`ow-tab-button`、`ow-drag-strip` 这类明确的壳层类名。最稳的做法不是“重新设计 sidebar”，而是在现有结构上加一个可切换的 sidebar state，并把 drag strip 的视觉噪音去掉。

**Primary recommendation:** 以 `App.tsx` 为壳层单点，增加 `sidebarCollapsed` 状态、收缩按钮和窄栏样式；`index.css` 只补少量 sidebar / drag 区清理样式，不把 Phase 1 扩展成全局 UI 重写。
</research_summary>

<standard_stack>
## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| React | 18.3.1 | 顶层壳层状态与条件渲染 | 已是当前应用主 UI 框架 |
| Tailwind CSS | 3.4.17 | 布局、间距、响应式和状态样式 | 当前页面和壳层均已大量使用 |
| `@tauri-apps/api` | 2.10.1 | 窗口拖拽、事件和宿主 API | 现有 App 壳层已在用 |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| TypeScript | 5.6.2 | 限定 tab 状态与 props 结构 | 修改壳层状态时保持静态约束 |
| Vite | 5.4.11 | 本地构建和 UI 快速验证 | 修改 App shell 后跑 build 验证 |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| 局部 `useState` 控制 sidebar | 全局 store / context | 当前需求太小，增加共享状态会扩大边界 |
| 保留现有 sidebar DOM 并条件显隐 | 引入独立 `Sidebar` 组件 | 未来可做，但这轮先收敛最小风险改动更合适 |

**Installation:**
```bash
cd mac-app
pnpm install --no-frozen-lockfile
```
</standard_stack>

<architecture_patterns>
## Architecture Patterns

### System Architecture Diagram

```text
User click collapse button
  -> App.tsx updates sidebarCollapsed state
    -> Sidebar width classes switch
    -> Nav items switch between icon+label and icon-only
    -> Auxiliary blocks hide in collapsed mode
    -> Main content container keeps current tab rendering

Window drag interaction
  -> Drag hotspot in App.tsx receives mouse down
    -> Tauri window API startDragging()
    -> Native window moves
```

### Recommended Project Structure
```text
mac-app/src/
├── App.tsx                 # 应用壳层与顶层导航
├── index.css               # 壳层共享样式 token 与公共类
├── pages/                  # 各 tab 页面
└── utils/appTabs.js        # 导航 tab 定义
```

### Pattern 1: Shell-local UI state
**What:** 由 `App.tsx` 持有仅影响应用壳层的本地状态，例如当前 tab、日志窗开关、首次运行 banner。  
**When to use:** 状态只影响壳层展示，不需要跨多个业务页面同步。  
**Example:** `activeTab`、`showLogs`、`isFirstRun` 已经是这种模式，`sidebarCollapsed` 应沿用同一模式。

### Pattern 2: Utility classes + `ow-*` shared classes
**What:** 结构布局用 Tailwind utility，视觉基线用少量 `ow-*` 全局类统一收口。  
**When to use:** 需要在多个壳层元素上共享边框、背景、阴影、交互规则时。  
**Example:** `ow-sidebar`、`ow-tab-button`、`ow-page-frame-soft` 已经在应用壳层和页面面板里复用。

### Anti-Patterns to Avoid
- **把 sidebar 收缩实现成完全隐藏:** 会破坏高频 tab 切换效率，也不符合用户刚刚明确的“保持窄栏”决定。
- **为了去掉虚线框而删掉拖拽能力:** 会直接破坏 macOS Tauri app 的窗口交互，属于功能回退。
- **顺手重做全局视觉系统:** 当前 phase 只收口导航壳层，扩大到所有页面会让验证面失控。

</architecture_patterns>

<dont_hand_roll>
## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| 壳层收缩状态 | 新的全局状态管理层 | `App.tsx` 本地 `useState` | 只影响单个壳层文件，没必要上全局状态 |
| 导航图标系统 | 新引入 icon 库 | 继续复用现有内联 SVG | 当前 tab 图标已存在，重引依赖没有收益 |
| 窗口拖拽行为 | 自己做浏览器级拖拽 hack | 继续复用 Tauri drag region + `startDragging()` | Tauri 已经提供原生窗口拖拽能力 |

**Key insight:** 这个 phase 的标准做法不是“加更多基础设施”，而是把现有壳层收口得更干净。
</dont_hand_roll>

<common_pitfalls>
## Common Pitfalls

### Pitfall 1: 收缩态只改宽度，不改内容布局
**What goes wrong:** sidebar 变窄后，文字、品牌卡片和底部状态块仍然挤在一起，视觉上更糟。  
**Why it happens:** 只处理容器宽度，没有同步处理内部块的显隐和对齐。  
**How to avoid:** 计划里必须把导航、品牌区和底部辅助块分别定义收缩态行为。  
**Warning signs:** 窄栏里出现文本截断、重叠或按钮热点过小。

### Pitfall 2: drag strip 视觉消失但热区也一起消失
**What goes wrong:** 虚线框没了，但窗口无法拖动。  
**Why it happens:** 直接删除节点或移除 `data-tauri-drag-region` / `onMouseDown`。  
**How to avoid:** 把“去样式”与“去热区”分开，优先保留热区，只清理视觉噪音。  
**Warning signs:** 构建通过，但安装态窗口顶部拖不动。

### Pitfall 3: 收缩态影响主内容区滚动或最小宽度
**What goes wrong:** sidebar 收缩后，`sessions` / `commands` 这类复杂页面出现溢出或内容挤压异常。  
**Why it happens:** 顶层 flex 容器宽度切换时，主内容区最小宽度和 overflow 约束没同步检查。  
**How to avoid:** 只调整 sidebar 宽度，不破坏 main 区 `flex-1 min-w-0` 的现有约束。  
**Warning signs:** 切换到 `Sessions` 或 `Commands` 后出现横向裁切或滚动异常。

</common_pitfalls>

<code_examples>
## Code Examples

### Existing shell-local state pattern
```tsx
const [activeTab, setActiveTab] = useState<AppTab>("dashboard");
const [showLogs, setShowLogs] = useState(false);
const [isFirstRun, setIsFirstRun] = useState(false);
```

### Existing Tauri drag integration pattern
```tsx
<div
  data-tauri-drag-region
  onMouseDown={handleWindowDrag}
/>
```

### Existing sidebar styling entry point
```css
.ow-sidebar {
  position: relative;
  background: var(--ow-sidebar);
  border-right: 1px solid var(--ow-line-soft);
}
```
</code_examples>

<sota_updates>
## State of the Art (2024-2025)

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| 单纯依赖复杂全局状态处理 app shell | 小范围 UI 状态优先本地化 | 持续演进 | 降低 layout 调整的耦合度 |
| 把桌面 UI 当网页 marketing layout 做大改 | 桌面工作台更强调密度、可扫描性和可预测导航 | 持续演进 | Phase 1 应偏“收口结构”，不是“做新视觉秀场” |

**New tools/patterns to consider:**
- `titleBarStyle: "Overlay"` 下的定制壳层拖拽热区复用已有模式即可，不需要额外插件。
- 通过 icon-only collapsed rail 提高桌面工作台密度，是当前较稳定的桌面产品模式。

**Deprecated/outdated:**
- 依赖明显装饰性 drag strip 作为“窗口框占位”的做法，不适合作为正式工作台 UI。
</sota_updates>

<open_questions>
## Open Questions

- 收缩按钮最终放在品牌区、导航区顶部，还是和品牌卡片同一行，需要在实现时结合现有层级做最小干扰选择。
- 是否给收缩态导航项补 `title` 或 tooltip，当前上下文没有强制要求，可在实现计划中决定。
</open_questions>

---

*Phase: 01-ui-foundation*
*Research completed: 2026-05-10*
