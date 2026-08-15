# Phase 22: Dark Mode Support - Context

**Gathered:** 2026-08-15
**Status:** Ready for planning

<domain>
## Phase Boundary

为已安装的 macOS App 增加 `System / Light / Dark` 三档主题，并让主窗口、所有现有页面与交互状态、menubar 展开面板保持一致。此阶段只改变主题选择、颜色和材质，不重排现有布局、不增加顶层页面、不改变 Provider、通知或会话业务行为，也不引入新依赖。

</domain>

<decisions>
## Implementation Decisions

### 主题切换规则与入口
- **D-01:** 提供 `System / Light / Dark` 三档主题，并持久化用户选择；首次启动默认 `System`。
- **D-02:** `System` 模式在应用运行期间实时跟随 macOS 外观变化。
- **D-03:** 主题选择器放在侧栏现有语言选择器附近，不新增 Settings 页面或顶层导航。
- **D-04:** 侧栏收起时隐藏主题选择器；需要切换时先展开侧栏。

### 视觉系统
- **D-05:** 暗色采用已选定的深蓝灰玻璃方向，不使用纯黑 OLED 或平面石墨方案；用户选择该方向的原因是整体色调更和谐。
- **D-06:** 保持当前页面布局、卡片尺寸、信息结构、内容密度和操作位置不变，只切换颜色、材质与主题控件。
- **D-07:** 浅色与暗色使用同一套层级、圆角、边框和语义色。浅色使用柔和的冷白/雾蓝玻璃材质；暗色使用深蓝灰半透明表面。两者都保留克制的蓝、绿、紫和琥珀语义色，避免霓虹、强光晕和装饰性重渐变。
- **D-08:** menubar 展开面板同步相同设计语言，同时保留现有总览、Provider 会话、用量与底部快捷入口，不增加信息或操作。

### 覆盖与系统联动
- **D-09:** 覆盖所有现有页面、表单、弹窗、下拉菜单、滚动区域以及 hover、focus、selected、disabled、loading、error 等交互状态，并覆盖 menubar 展开面板。
- **D-10:** macOS 外观变化时，主窗口与 menubar 展开面板立即同步。
- **D-11:** 在 React 首帧渲染前应用持久化主题或系统主题，避免亮色闪屏。
- **D-12:** 手动切换时仅对颜色、背景、边框和阴影使用约 `150ms` 的轻微淡变；不做整窗淡入淡出，并尊重减少动态效果偏好。

### the agent's Discretion
- 在上述视觉方向内确定精确 token 数值、存储键名称和最小代码组织方式。
- 选择 Tauri 已有 app/window 主题 API 与浏览器系统主题监听的最小可靠组合，但不得新增主题依赖。
- 决定测试文件如何拆分；必须保留至少一组可运行回归，覆盖持久化、系统跟随、首帧主题和 menubar 同步。

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### 产品与范围
- `.planning/PROJECT.md` — installed-app-first 产品边界、macOS 目标与现有技术栈约束。
- `.planning/ROADMAP.md` — Phase 22 位置、依赖与阶段边界。
- `docs/screenshots/dashboard.png` — 当前主界面布局基准；主题实现不得重排该结构。

### 主窗口主题入口
- `mac-app/src/App.tsx` — 侧栏折叠、语言分段控件、主页面导航和共享 App shell。
- `mac-app/src/main.tsx` — 主窗口与 menubar 窗口的共同 React 启动入口；首帧防闪必须在此入口之前或之中完成。
- `mac-app/src/index.css` — 现有 `--ow-*` 色彩/表面 token、共享玻璃表面和全局状态样式。
- `mac-app/tailwind.config.js` — 当前 Tailwind 配置；不得为主题支持引入额外依赖。

### Menubar 与原生窗口
- `mac-app/src/components/menubar-popover/MenubarPopover.tsx` — menubar 展开面板的现有信息结构与硬编码浅色样式。
- `docs/superpowers/specs/2026-07-07-menubar-popover-design.md` — menubar 是紧凑入口而非迷你 Dashboard 的既有设计约束。
- `mac-app/src-tauri/capabilities/default.json` — 主窗口与 menubar 的 Tauri 权限边界；使用原生主题 API 时需最小化新增权限。

### 回归测试
- `mac-app/tests/appShell.test.mjs` — App shell、侧栏和共享入口的现有源级回归模式。
- `mac-app/tests/menubarPopover.test.mjs` — menubar 结构与行为的现有源级回归模式。

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `mac-app/src/index.css` 已有 `--ow-sidebar`、`--ow-panel`、`--ow-text`、语义色和阴影变量，可扩展为浅/深两套 token，无需引入主题库。
- `mac-app/src/App.tsx` 的语言分段控件可直接复用交互与视觉结构，增加三档主题选择器。
- 当前已安装的 `@tauri-apps/api` 提供 app/window 主题设置与主题变化监听能力，可复用原生平台能力。
- `MenubarPopover` 已包含完整数据、导航和交互结构，本阶段只需主题化现有组件。

### Established Patterns
- `mac-app/src/main.tsx` 同时承载主 App 的懒加载入口和 menubar 的直接入口，且两者共享 `index.css`；主题初始化应保持单一来源。
- 主界面大量使用现有 `ow-*` 表面类，同时仍有 `bg-white`、`text-slate-*` 等浅色 Tailwind 类；实现需要覆盖这些现有表面，但不得借机重构页面结构。
- macOS 安装包是运行真相；源级验证完成后，打包安装验证仍需按仓库规则另行获得用户明确许可。

### Integration Points
- 在 React 渲染前解析持久化偏好与系统外观，并把解析后的主题写到根元素，避免首帧闪烁。
- App shell 管理用户选择；原生 app 主题和根元素主题状态需保持同步，使主窗口和 menubar 使用同一结果。
- 主题 token 与必要的 Tailwind 状态样式覆盖所有页面和 menubar；只迁移颜色/材质相关类，不触碰布局和业务逻辑。
- Tauri capability 只增加调用既有主题 API 所需的最小权限。

</code_context>

<specifics>
## Specific Ideas

- 暗色基调为深蓝灰而非纯黑，表面之间用细冷灰边框和轻微透明度形成层次；主文字使用柔和的近白色。
- 浅色是暗色的日间对应版本：冷白与雾蓝背景、半透明白色表面、深蓝灰文字；不是对现有页面重新设计。
- 主题选择器与语言选择器保持同类分段控件表达，显示 `System / Light / Dark`。
- menubar 继续保持约 `420px` 宽的紧凑弹出层，不添加新卡片、指标或操作。

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 22-Dark Mode Support*
*Context gathered: 2026-08-15*
