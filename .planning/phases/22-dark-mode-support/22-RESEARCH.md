# Phase 22 Research: System / Light / Dark 主题支持

**日期：** 2026-08-15  
**阶段：** Phase 22 — Dark Mode Support  
**范围：** 已安装 macOS App 的主窗口、现有页面/表单/弹窗/交互状态、menubar popover。只改变颜色、材质和主题控件；不重排布局、不改变 Provider/通知/Session 业务、不新增依赖。

## 结论摘要

推荐一条很窄的实现链：

1. 在 `index.html` 的首个脚本之前用极小同步 bootstrap 读取 `localStorage` 的 `System / Light / Dark` 偏好并设置 `<html data-ow-theme="light|dark">`；`main.tsx` 再调用同一个共享 theme 模块完成运行时监听。
2. 用一个 `mac-app/src/utils/theme.ts` 承载偏好校验/持久化、System 解析、DOM 应用、Tauri window-theme 设置和跨窗口同步；`App` 只负责选择器状态，`MenubarPopover` 不复制主题状态。
3. 把 `index.css` 现有 `--ow-*` 扩成最小语义 token 层，先把 `ow-*` 共用表面改为 token，再按页面分组清理 `bg-white`、`text-slate-*`、`border-*-*` 等硬编码颜色。不要加入 Tailwind dark variant 或主题库。

这条链满足用户锁定的首帧防闪、System 实时跟随、主窗口/menubar 同步和后续 UI 可复用，同时保持当前布局和业务组件边界。

## 已核验的上下文与代码事实

- Phase 22 的范围与锁定决策在 `22-CONTEXT.md:9-37`：默认 `System`、持久化、运行时跟随 macOS，选择器靠近语言控件，覆盖所有页面/状态/menubar，手动切换仅约 `150ms` 的颜色淡变并尊重减少动态效果。
- `ROADMAP.md:854-863` 目前只有 Phase 22 的 goal/requirements 占位，依赖 Phase 21，尚无计划。
- `STATE.md:1-13, 201-215` 显示当前停止点为“Phase 22 context gathered”；Phase 21 的安装态验证已完成，但本阶段安装包验证仍须单独取得当前对话的明确许可。
- 当前 `.planning/REQUIREMENTS.md:1-44` 没有新的主题 requirement；主题规则来自 Phase 22 context，不应把旧的 `UX-01` 回填成新的业务需求。
- `mac-app/src/main.tsx:1-5, 26-37` 是两个窗口的共同 React 入口：通过 `getCurrentWindow().label` 在 `main` 与 `menubar-popover` 之间选择内容，然后 `ReactDOM.createRoot`。这是首帧初始化和共享监听的唯一入口。
- `mac-app/src/MainApp.tsx:4-9` 只给主窗口包 `I18nProvider`；menubar 直接渲染 `MenubarPopover`，所以主题不能依赖主窗口 React context。
- `mac-app/src/App.tsx:65-75` 保存主壳层状态；`330-375` 是现有语言选择器和收起侧栏分支，正好是主题选择器的落点；`403-505` 路由所有现有页面；`510-515` 挂载 `LogWindow` 弹窗；`520-525` 是页面加载 spinner。
- `mac-app/src/components/menubar-popover/MenubarPopover.tsx:58-85` 是独立 popover 生命周期；`261-370` 保留总览、Provider、Usage 和底部 Tasks/Sessions/Usage 入口。它目前不读取任何主题状态，结构本身不应被重排。
- `mac-app/src/index.css:5-27` 已有 `--ow-sidebar`、`--ow-panel`、`--ow-panel-soft`、`--ow-line`、`--ow-text`、语义色和三档阴影；`68-260` 已有共享玻璃表面、按钮、segment、modal、log 样式。`main.tsx:20` 使用了 `var(--ow-bg)`，但 `index.css:5-27` 未定义该 token，应在主题 token 层补上。
- `mac-app/tailwind.config.js:1-6` 没有 `darkMode` 配置，也没有额外插件。用 CSS data attribute + 变量即可，不需改变 Tailwind 配置。
- `mac-app/src-tauri/capabilities/default.json:5-12` 已将 capability 应用于 `main` 和 `menubar-popover`，已有 `core:event:default` 与 `core:window:default`。
- menubar 原生窗口在 `mac-app/src-tauri/src/menubar.rs:205-226` 设置了 `.decorations(false)`、`.transparent(true)`、透明背景、置顶和无阴影；`MenubarPopover.tsx:68-85` 又把 html/body/root 临时设为透明。暗色面板必须保留透明外壳，并把实际层次放到 token 化的 panel 上。
- `mac-app/src/i18n/index.tsx:13,31-47` 已使用 `localStorage` key、惰性初始值和写回 effect；主题偏好可以复用这一成熟的浏览器标准模式，但不能复用 I18n context，因为 menubar 不在该 provider 下。

## 推荐主题状态与边界

主题应明确分成两个值，避免把用户偏好和当前渲染结果混在一起：

| 值 | 允许值 | 责任 |
| --- | --- | --- |
| `ThemePreference` | `system \| light \| dark` | 选择器和 `localStorage` 的持久化值；缺失、非法或读取失败时为 `system` |
| `ResolvedTheme` | `light \| dark` | 由 preference + 当前系统外观解析出的 DOM/CSS 结果 |

建议 key 为 `onlineworker.theme`，首次启动不写入也按 `system` 渲染；用户第一次选择后再写入。`System` 的解析只使用 `window.matchMedia("(prefers-color-scheme: dark)")` 和 Tauri native theme event，不进入 `config.yaml`、Rust app state、Provider 配置或业务 EventBus。

共享模块的最小 API 可以是：

```ts
type ThemePreference = "system" | "light" | "dark";
type ResolvedTheme = "light" | "dark";

readThemePreference(): ThemePreference;
resolveTheme(preference, systemTheme): ResolvedTheme;
applyResolvedTheme(theme): void;
setThemePreference(preference): Promise<void>;
installThemeSync(): () => void;
```

不要创建完整的 Design System、React ThemeProvider 或状态管理依赖。`App` 只调用 `readThemePreference` 初始化选择器、调用 `setThemePreference` 更新选择；两个 webview 都由 `main.tsx` 调用 `installThemeSync`，DOM 的 `data-ow-theme` 是两窗口唯一消费边界。

## 首帧初始化、持久化与运行时联动

### 首帧

`main.tsx` 的静态模块会先加载 CSS（`main.tsx:1-5`），因此只在 React render 前设置属性仍可能留下 webview 默认白底的短暂闪烁。推荐在 `mac-app/index.html:1-11` 的 `<head>` 中加入极小的同步 bootstrap：读取 `onlineworker.theme`，只接受三个合法值，读取 `matchMedia` 解析 `system`，同步写入 `document.documentElement.dataset.owTheme`。它不引入模块、不触碰业务，也不执行异步 Tauri 调用。

`main.tsx` 随后仍应在构造 `content`/`createRoot` 前调用共享模块的同步初始化；这既是 bootstrap 的兜底，也让 source-mode/Vite、未来入口和测试都遵守同一契约。bootstrap 与共享模块必须使用同一 key/合法值；`theme.test.mjs` 应检查二者没有漂移。

### 用户切换与持久化

1. `App.tsx:330-375` 的展开侧栏中，沿用语言 segment 的尺寸、圆角和布局，增加 `System / Light / Dark` 三项；收起分支保持隐藏，不新增 Settings tab。
2. 选择时先同步写 `localStorage`、同步 `applyResolvedTheme`，再调用 `getCurrentWindow().setTheme(...)` 并广播 `app:theme-changed`；这样 UI 不等待 IPC，另一个窗口也能立即同步。
3. `system` 调用 native `setTheme(null)`，`light/dark` 调用 native `setTheme("light"|"dark")`。native 调用或跨窗口事件失败时保留 DOM/偏好结果，并在开发日志中记录，不让主题错误阻塞业务。
4. `localStorage` 读取/写入异常、非法值、SSR/非浏览器环境都回退到 `system`/当前媒体查询；不得让首帧因为主题存储失败而白屏。

### 主窗口与 menubar 同步

- `installThemeSync` 在每个窗口监听 `getCurrentWindow().onThemeChanged`；只有偏好为 `system` 时才用 event payload 覆盖 DOM，这样显式 `Light/Dark` 不会因系统变化被误改。
- 同时监听 `matchMedia` 的 `change` 事件，作为 source-mode 和 Tauri 事件不可用时的标准浏览器 fallback；兼容旧 webview 可提供 `addListener/removeListener` fallback。
- 监听 Tauri `app:theme-changed` 自定义事件作为主窗口到 menubar 的实时同步通道；`localStorage` 仍是持久化和错过事件后的启动兜底。`storage` 事件只作为 source-mode/browser fallback，不依赖它承担两个 WKWebView 的唯一同步责任。
- 监听器返回 cleanup，处理异步 `onThemeChanged(...).then(unlisten)` 在窗口销毁前后完成的竞态；这对 menubar warmup/hide 生命周期尤其重要。
- `setTheme` 只从主窗口的选择器发起；menubar 不提供第二套设置入口，也不重复写偏好。menubar 只执行 bootstrap + shared sync，避免两套控制器漂移。

## Tauri 原生 API 与最小 capability

本地已安装 `@tauri-apps/api@2.10.1`，无需增加依赖：

- `mac-app/node_modules/@tauri-apps/api/app.d.ts:166-181` 也提供 app 级 `setTheme`，但当前入口已经使用 window API，本阶段不需要再引入第二套调用与权限。
- `mac-app/node_modules/@tauri-apps/api/window.d.ts:40` 定义 `Theme = 'light' | 'dark'`；`489` 提供 `theme(): Promise<Theme | null>`；`1155-1164` 提供 `setTheme`，并明确 macOS/Linux 下是 app-wide；`1291-1307` 提供 `onThemeChanged`。
- `window.js:612-615` 的 `theme()` 调用 `plugin:window|theme`；`1547-1551` 的 `setTheme()` 调用 `plugin:window|set_theme`；`1767-1769` 的 `onThemeChanged()` 监听 `tauri://theme-changed`。
- `mac-app/src-tauri/gen/schemas/desktop-schema.json:1440-1443` 显示现有 `core:window:default` 已包含 `allow-theme`；`1830-1834` 单独列出 `core:window:allow-set-theme`。
- `mac-app/src-tauri/gen/schemas/desktop-schema.json:462-465` 单独列出 `core:app:allow-set-app-theme`；`core:app:default` 当前只有版本/名称/监听等权限（同文件 `398` 附近定义，且 `default.json:7-10` 使用 `core:app:default`）。

推荐在 `mac-app/src-tauri/capabilities/default.json:6-11` 只新增：

```json
"core:window:allow-set-theme"
```

使用现有 `getCurrentWindow().setTheme`；Tauri 明确说明该 API 在 macOS/Linux 上是 app-wide，因此不再申请 `core:app:allow-set-app-theme`。现有 `core:event:default` 已覆盖跨窗口 listen/emit。修改 capability 属于根配置变更，实施前应记录影响面并跑 Tauri build/安装态检查。

## 可复用语义 token 层

### 原则

`index.css` 是现有主题真相源，应保留现有 `--ow-*` 命名作为兼容层，并新增少量语义名。建议两套值放在 `:root[data-ow-theme="light"]` 和 `:root[data-ow-theme="dark"]`（bootstrap 一定会设置属性）；不要为每个页面复制一套颜色，也不要把 RGB 常量藏进 TSX。

推荐的最小 token 集（数值是实现起点，落地时以实际对比度和安装态截图校准）：

| 语义组 | token | Light 起点 | Dark 起点（深蓝灰玻璃） |
| --- | --- | --- | --- |
| 背景 | `--ow-bg` | `#edf3fa` | `#0b1220` |
| 表面 | `--ow-surface` / `--ow-surface-soft` | `rgba(255,255,255,.90)` / `rgba(248,250,252,.84)` | `rgba(24,36,55,.88)` / `rgba(31,47,69,.72)` |
| 交互表面 | `--ow-surface-hover` / `--ow-surface-selected` | `rgba(255,255,255,.96)` / `rgba(231,240,255,.92)` | `rgba(48,67,94,.78)` / `rgba(49,75,110,.82)` |
| 输入/代码 | `--ow-input` / `--ow-code` | `rgba(255,255,255,.92)` / `#0f172a` | `rgba(16,26,42,.92)` / `#0a1424` |
| 边框 | `--ow-line` / `--ow-line-soft` | `rgba(148,163,184,.22)` / `rgba(148,163,184,.14)` | `rgba(148,163,184,.30)` / `rgba(148,163,184,.18)` |
| 文字 | `--ow-text` / `--ow-muted` / `--ow-subtle` | `#172033` / `#64748b` / `#94a3b8` | `#e6eef8` / `#a7b8cc` / `#7f93ac` |
| 文字反色 | `--ow-inverse` | `#ffffff` | `#07101c` |
| 交互 | `--ow-accent` / `--ow-accent-hover` / `--ow-focus` | `#2563eb` / `#1d4ed8` / `rgba(37,99,235,.30)` | `#62a5ff` / `#86bfff` / `rgba(98,165,255,.44)` |
| 状态 | `--ow-success`, `--ow-warning`, `--ow-danger`, `--ow-info` 及各自 `-soft` | 复用现有绿/琥珀/玫红/蓝及浅色 soft | 提高明度、降低 soft 不透明度，保证文字/背景对比度 |
| 阴影 | `--ow-shadow-sm/md/lg` | 保留现有三档 | 使用更深蓝黑、较低扩散，避免黑块和强光晕 |
| 覆盖层 | `--ow-overlay` | `rgba(15,23,42,.20)` | `rgba(2,8,23,.58)` |

兼容映射建议：现有 `--ow-sidebar`、`--ow-panel`、`--ow-panel-soft`、`--ow-line`、`--ow-line-soft` 保留为组件消费名，并由它们引用上述 `--ow-surface*`；现有 `--ow-blue*`、`--ow-green*`、`--ow-amber*`、`--ow-red*`、`--ow-purple*` 也保留为 provider/状态兼容别名。新 UI 只允许消费语义 token 或现有 `.ow-*` 组件类，不再新增 `bg-white`、`text-gray-*`、`border-slate-*` 等主题硬编码。

### 消费规则与增量约定

1. 背景、面板、输入、代码块、modal backdrop、表格 header、滚动条 thumb 一律消费 token；白色只允许出现在明确的反色图标/按钮文字语义中。
2. `hover/selected/focus/disabled/loading/error` 用 surface/interactive/status token 组合；不为单个页面创造新的 RGB 值。focus 必须有可见 ring/border，disabled 不能只依赖 opacity。
3. provider accent 仍由 `mac-app/src/utils/menubarPopover.ts:35-94` 统一返回 class/token（已有 `var(--ow-blue*)`、`var(--ow-purple*)` 等），不要在 menubar 和主窗口分别写一套 Codex/Claude 色值。
4. 现有 `.ow-page-frame`、`.ow-page-frame-soft`、`.ow-toolbar`、`.ow-segment`、`.ow-btn`、`.ow-btn-primary`、`.ow-modal-*`、`.ow-log-*` 是最小可复用组件表面；新 UI 优先组合它们，不为未来假设建立组件库。
5. 新增 token 时只在 `index.css` 两个主题块定义，同时更新 `docs/UI-THEME.md`、token contract test 和消费点；禁止在 TSX 写一处主题色再“以后抽取”。
6. 主题切换过渡只作用于 `color/background-color/border-color/box-shadow/fill/stroke`，约 `150ms`；不要用整窗 opacity 或让 `transition-all` 造成布局/transform 动画。`@media (prefers-reduced-motion: reduce)` 下将主题过渡和非必要 spinner/transform 动画降为 0 或最短可接受值。

## 页面、弹窗、表单和状态覆盖盘点

### 入口和页面路由

`App.tsx:403-505` 是当前用户可见内容的完整分发：

| 区域 | 现有实现/证据 | 必须覆盖的主题状态 |
| --- | --- | --- |
| App shell/sidebar/拖拽区 | `App.tsx:241-328,378-409`；品牌卡、收起按钮、tab、attention badge、主表面 | normal/hover/selected/focus/disabled、侧栏收起；不改宽度和布局 |
| Dashboard | `App.tsx:411-419` → `pages/Dashboard.tsx:120-184`；`components/dashboard/*` | provider healthy/warning/error/neutral、service start/stop/restart、loading、alerts、ActionGuideDialog |
| Task Board | `App.tsx:420-427` → `pages/TaskBoard.tsx:198-252,300-419,962-1215` | needs-attention/running/recent-ended lane、selected/pinned、approval allow/deny、interrupt/recover/continue、loading/error/empty、移动详情 |
| Sessions | `App.tsx:497-505` → `pages/SessionBrowser.tsx:719-850` | provider/workspace/session selected/hover、new-session composer、archive active/archived、context/action menu、loading/error/empty、chat/code/attachments |
| Usage | `App.tsx:492-495` → `pages/UsageBrowser.tsx:187-395` | provider segment、date inputs、apply disabled/loading、chart bars、sticky table header/rows、unsupported/error/empty |
| Commands | `App.tsx:487-490` → `pages/CommandRegistry.tsx:308-500` | search focus、backend/secondary segment、checkbox checked/hover、publish/refresh disabled/loading、notice/warning/success/error、empty/loading |
| Setup | `App.tsx:444-485` → `pages/SetupWizard.tsx:205-513` | 4 个步骤、done/pending/checking/not-found、展开说明、token/password reveal、输入 focus/disabled、launch/saving/error |
| Settings panels | `App.tsx:469-484`；`ProviderSettingsPanel.tsx:381-701`、`NotificationSettingsPanel.tsx:287-539`、`AiSettingsPanel.tsx:224-297`、`MaintenanceSettingsPanel.tsx:195-371`、`ConfigEditor.tsx:104-166` | provider/channel/service/scenario toggle、select/input/textarea、saved/saving/test/error、diagnostic pass/warning/fail、YAML/env view/edit/save/empty |

### 弹窗、菜单和共享状态

- `App.tsx:510-515` 挂载 `LogWindow`；`LogWindow.tsx:91-230` 是 modal backdrop/panel、level badge（`10-30`）、filter chips、auto-scroll checkbox、live/paused、空态和日志行。
- `Dashboard.tsx:169-184` 挂载 `ActionGuideDialog`；`ActionGuideDialog.tsx:72-165` 使用 portal、modal、步骤、命令 code block、copy/primary/secondary/close，必须覆盖 backdrop、focus、disabled 和错误/提示语义。
- `SessionBrowser.tsx:825-849` 挂载 `SessionActionMenu`/`WorkspaceActionMenu`；`components/session-browser/archive.tsx:59-92`、`workspaceActions.tsx:70` 使用硬编码浅色菜单表面。
- `components/ConnectivityTest.tsx:107-161` 有 idle/running/pass/fail；`components/CliChecker.tsx:89-164` 有 checking/installed/not-found/install hint；二者都属于 Setup/Settings 可见状态。
- `components/session-browser/navigation.tsx:28-352`、`presentation.tsx:80-96`、`shared.tsx:366-...`、`GenericProviderChat.tsx` 覆盖 Session 侧栏、列表、聊天、StatePanel、composer 和附件交互；不能只修 `SessionBrowser.tsx` 根节点。
- `components/ai-settings/AiServiceEditor.tsx:59-195`、`AiScenarioEditor.tsx:42-142`、`fields.tsx:50-94` 是表单输入/选择/textarea 的主要硬编码来源；`ProviderSettingsPanel.tsx:577-686` 还有 launch-method/CLI code 输入。

### 现有硬编码颜色的高风险证据

这不是可用一个 dark class 覆盖的少数点：

- App shell 直接写 `bg-white/72`、`text-gray-*`、`bg-rose-*`、`bg-emerald-*`：`App.tsx:251-320,330-369,388-395`。
- menubar 主表面、header、nav、main、footer 和 session rows 直接写 `bg-white`/`border-slate-*`/`text-slate-*`：`MenubarPopover.tsx:261-370,397-432,460-513,518-570,605-736`。
- TaskBoard 用 provider hash 产生多套 utility 字符串，lane/status/approval/detail 全是浅色类：`TaskBoard.tsx:198-252,312,401-419,1008-1046,1056-1208`。
- Usage 的图表颜色是 TSX 内 `rgba` gradient 数组：`UsageBrowser.tsx:35-44`；控件、sticky header、表格仍有 `bg-white`/`bg-slate-50`：`244-365`。
- CommandRegistry 甚至在 JSX `<style>` 内硬编码 checkbox `#fff/#d1d5db/#3b82f6`：`CommandRegistry.tsx:310-347`；搜索、filters、warnings、list header 在 `350-493` 仍大量浅色 utility。
- Setup 的步骤色、status badge、说明 panel、密码/ID/chat 输入在 `SetupWizard.tsx:216-410` 直接使用 green/blue/violet/rose/amber/gray 和 `bg-white`。
- ConfigEditor 的 raw code/editor、view/edit segmented、save/error/empty 在 `ConfigEditor.tsx:9-31,49-149,156-165`；textarea `bg-white` 与 dark code block 必须分别落到 `--ow-input`/`--ow-code`。
- Log level 样式表 `LogWindow.tsx:10-30`、日志行 `205-222` 是状态 token 迁移的集中点；ActionGuide modal 的步骤/code/note/按钮在 `ActionGuideDialog.tsx:85-155`。
- Provider/Notification/AI/Maintenance panels 的典型硬编码分别见 `ProviderSettingsPanel.tsx:384-686`、`NotificationSettingsPanel.tsx:290-525`、`AiSettingsPanel.tsx:227-259`、`MaintenanceSettingsPanel.tsx:198-362`。

### 最小迁移策略

按“共用面先行、页面颜色后行”拆，不重排 DOM/grid/宽高：

1. **Token/CSS 基础：** 在 `index.css` 定义 light/dark token、`data-ow-theme` 选择器、`--ow-bg`，把现有 `.ow-*` 表面/滚动条/modal/log/segment/button 改为 token；保留旧 token alias。
2. **入口/选择/同步：** 新增共享 theme module，更新 `index.html`、`main.tsx`、`App.tsx`、`default.json`；先验证主窗口和 menubar 的 DOM attr/native event 同步。
3. **Menubar：** 只迁移 `MenubarPopover.tsx` 的结构颜色和 `utils/menubarPopover.ts` 的消费名，保留当前 snapshot、tabs、rows、透明外壳和约 `420px` 紧凑信息结构；不能用主题工作重做 popover 设计。
4. **主页面：** 依次迁移 App shell → Dashboard/TaskBoard/SessionBrowser → Usage/CommandRegistry/Setup；仅替换颜色、材质、ring、状态 token。TaskBoard 的 provider accent 和 Usage chart 应改成 token/CSS 变量，不改 hash 选择和数据行为。
5. **设置与弹窗：** 迁移 Config/Provider/Notification/AI/Maintenance、CLI/connectivity、LogWindow、ActionGuideDialog、Session menus/chat；集中抽取 input/select/textarea/code/status 的语义类，避免每个组件再次写白色。
6. **硬编码漏网门禁：** 运行 source scan；允许 provider brand/icon 图片、纯 SVG `currentColor`、明确的 `--ow-*` 引用和反色按钮文字，其余新加主题色必须通过 token。扫描应在测试/文档中可复现，而不是一次性人工搜索。

## 主窗口与 menubar 的共同入口方案

建议 `main.tsx` 保留当前“label 分流 + 单一 `createRoot`”结构，不把主题逻辑塞进 `App` 或 `MenubarPopover` 各写一份：

```text
index.html inline bootstrap
        ↓ (同步 data-ow-theme)
main.tsx: initialize + installThemeSync
        ├── label=main            → MainApp → App (唯一选择器/偏好写入者)
        └── label=menubar-popover → MenubarPopover (只消费 DOM + sync)
```

`MainApp` 的 I18n 边界保持不变；theme module 不依赖 I18n。`MenubarPopover` 仍可保留 `68-85` 的透明背景 effect，但其实际 panel/header/nav/main/footer 必须统一 token。主窗口与 menubar 不应互相 `invoke` 业务命令来同步主题；Tauri event、native theme event、持久化兜底和同一 `data-ow-theme` 合约足够。

## 建议实施任务拆分

这是给后续 plan 的最小可验证切片；每片只触碰对应颜色/主题边界：

### 22-01 — Theme contract and bootstrap

- **创建：** `mac-app/src/utils/theme.ts`。
- **修改：** `mac-app/index.html`、`mac-app/src/main.tsx`、`mac-app/src-tauri/capabilities/default.json`。
- **内容：** 偏好类型/校验、首帧 attr、`matchMedia`/storage/native event、自定义 `app:theme-changed` 事件、window `setTheme`、cleanup；只增加 `core:window:allow-set-theme`。
- **验证：** pure Node test + `appShell`/`bundleSplitting` source contract + `tsc`。

### 22-02 — Semantic tokens and reusable UI rules

- **修改：** `mac-app/src/index.css`；把旧 `--ow-*` 作为 alias，新增 token 主题块、reduced-motion、theme transition；不改 Tailwind config。
- **创建/更新：** `docs/UI-THEME.md`，并在 `docs/README.md`/`CONTRIBUTING.md` 增加开发者入口链接（见下节）。
- **内容：** token 表、组件消费规则、增量扩展约定、禁止新 UI 硬编码、对比度/状态/透明窗口规则。
- **验证：** token contract test 读取 CSS + docs；人工抽查 token 消费；`git diff --check`。

### 22-03 — App shell and menubar parity

- **修改：** `mac-app/src/App.tsx`、`mac-app/src/components/menubar-popover/MenubarPopover.tsx`、必要时 `mac-app/src/utils/menubarPopover.ts`。
- **内容：** 侧栏语言旁三档选择器、main/menubar 共用 attr/native sync、menubar 原有结构全量 token 化；不添加 menubar 主题入口，不改布局。
- **验证：** `appShell.test.mjs`、`menubarPopover.test.mjs`、theme sync source test；source-mode 主窗口/menubar 双入口 smoke。

### 22-04 — Existing surfaces color-only migration

- **修改：** `mac-app/src/pages/{Dashboard,TaskBoard,SessionBrowser,UsageBrowser,CommandRegistry,SetupWizard}.tsx`、`mac-app/src/components/dashboard/*`、`components/session-browser/*`、`components/{ConfigEditor,ProviderSettingsPanel,NotificationSettingsPanel,AiSettingsPanel,MaintenanceSettingsPanel,CliChecker,ConnectivityTest,ActionGuideDialog,LogWindow}.tsx`、`components/ai-settings/*`。
- **内容：** 只替换颜色/材质/ring/status/disabled/loading/error；保留现有 grid、尺寸、数据调用和交互顺序。
- **验证：** 全前端 Node tests、`tsc --noEmit`、`pnpm build`、hardcoded-color scan；至少逐页检查两主题和关键状态。

### 22-05 — Installed visual and runtime acceptance

- 只有在用户明确允许后运行打包/安装/重启；按仓库 fast packaged chain 或完整链路选择验证深度。
- 安装态需验证主窗口、menubar 透明边缘、两窗口同步、首次启动 `System`、持久化 `Light/Dark`、macOS 外观切换和减少动态效果。
- 不把源级测试、构建成功或 `open` 请求单独声称为安装态完成。

## 正式开发文档落点

当前没有稳定的 UI theme 开发文档：`docs/README.md:1-35` 只记录截图和公共支持材料；`docs/superpowers/specs/2026-07-07-menubar-popover-design.md:1-5` 是日期化的 popover 草案，不适合作为所有后续 UI 的 token 规范。

推荐创建一份稳定公共文档 `docs/UI-THEME.md`，内容包括：

- `ThemePreference`/`ResolvedTheme`、key、首帧 bootstrap、Tauri/native 和 browser fallback 边界。
- 完整语义 token 名称及 light/dark 值；现有 alias 的兼容说明。
- `.ow-*` 表面/按钮/segment/modal/log 的消费规则、状态/对比度/透明 menubar 规则。
- 新 UI 增量约定：只能消费 token/既有语义类；新增 token 必须同时更新 CSS、文档、contract test；禁止再写 `bg-white` 等主题硬编码；布局不能借主题迁移重排。
- 验收矩阵和 `prefers-reduced-motion` 规则。

文档索引建议：

- 更新 `docs/README.md` 的 Contents，链接 `UI-THEME.md`；它是现有 docs 入口，改动面最小。
- 在 `CONTRIBUTING.md` 的代码风格/验证附近加一条“前端 UI 主题规则见 `docs/UI-THEME.md`”，让后续贡献者能找到正式规范。
- 不必把 token 细节塞进 `README.md`/`README.zh.md`，避免面向用户的产品首页变成开发规范；`docs/superpowers/specs/...menubar...` 只需在必要时链接到稳定文档，不作为 token 真相源。

计划必须包含“实现代码 token 与 `docs/UI-THEME.md` 一致”的验证：建议 `mac-app/tests/themeContract.test.mjs` 读取 docs 中的 `--ow-*` 列表并断言每个 token 在 `index.css` 中出现，且断言 docs 不再引用已删除 token；再配合 `node --test tests/themeContract.test.mjs`。本轮遵守用户边界，不修改该正式文档。

## Validation Architecture

验证分为可运行源级契约、构建级检查和安装态视觉/系统检查三层；任何一层不能替代另一层。

### 1. 可运行源级契约

建议新增 `mac-app/tests/theme.test.mjs`（纯函数行为）和 `mac-app/tests/themeContract.test.mjs`（文件契约），沿用现有 Node 原生测试风格：

- 偏好：缺失/非法值 → `system`；`light/dark` 持久化并可读回；不写入业务 config。
- 解析：`resolveTheme("system", "dark")`/`("system", "light")` 正确；显式模式不受系统变化影响。
- 首帧：bootstrap key/合法值/data attribute 与 shared module 一致；`main.tsx` 在 `createRoot` 前初始化。
- 同步：`main.tsx` 和 menubar 入口都安装同一 sync；native `onThemeChanged`、`matchMedia`、`storage` 分支存在；没有第二套 menubar preference writer。
- token：文档声明的 token 在 light/dark CSS 块中存在；现有 `--ow-*` alias 不被删；`--ow-bg` 已定义。
- 页面覆盖：source contract 断言 App 选择器、menubar 结构、modal/setting/page 根节点保留；不把主题迁移误改为 layout/业务重构。

### 2. 推荐可运行命令

```bash
cd mac-app
node --test tests/theme.test.mjs tests/themeContract.test.mjs tests/appShell.test.mjs tests/menubarPopover.test.mjs
node --test tests/*.test.mjs
./node_modules/.bin/tsc --noEmit
pnpm build
```

在仓库根目录补充：

```bash
git diff --check
rg -n --glob '*.{tsx,ts,js,css}' '(bg-white|text-(gray|slate)-|border-(gray|slate)-|#[0-9A-Fa-f]{3,8}|rgba\()' mac-app/src
```

最后一个扫描是人工审查输入，不应机械地把 provider brand/icon、SVG `currentColor`、合法 `--ow-*` 引用或明确的 code/反色语义判成错误；但新增 UI 的主题颜色应为零个未解释命中。建议把允许例外写入 test/文档，而不是永久忽略整目录。

### 3. Source-mode / visual checks

- 用 dev app 打开 Dashboard、Task Board、Sessions、Usage、Commands、Setup、AI、Notifications、Maintenance、Advanced Config；逐一切换 Light/Dark/System。
- 对每页至少检查 normal、hover、focus、selected、disabled、loading、empty、warning/error；检查表单输入、select、textarea、code block、滚动条和 modal。
- menubar popover 要在透明窗口背景上检查圆角边缘、panel/header/nav/footer、provider accents、空态和 refresh/loading；不新增内容、不改变宽度/高度/信息结构。
- 检查 `prefers-reduced-motion: reduce` 下主题切换没有整窗淡入淡出，颜色过渡被关闭/缩短，现有 loading spinner 不造成明显额外动画风险。

### 4. 安装态边界

主题支持触碰 Tauri capability、原生窗口 theme、透明 menubar 和两个 webview，安装包是运行真相。只有得到当前对话明确许可后，才能执行仓库规定的 `bash scripts/verify-packaged-fast.sh` 或完整 build/install/relaunch 链；未获许可时只能报告 source/build 验证，不能声称安装态通过。

安装态矩阵至少包含：

| 场景 | 验收 |
| --- | --- |
| 首次启动 | 无历史 key 时是 `System`；当前 macOS 外观和首帧背景一致，无亮色闪屏 |
| 手动持久化 | Light/Dark 重启后仍一致；两个窗口相同；native chrome 与 web content 同色调 |
| System 跟随 | macOS Light ↔ Dark 时主窗口和已存在/新打开 menubar 同步；显式 Light/Dark 不跟随 |
| 所有入口 | 主窗口每页、弹窗、菜单、表单和状态覆盖；menubar 总览/Provider/Usage/底部入口保持原结构 |
| 透明/材质 | menubar 透明外壳不露白、不出现纯黑块；玻璃层级和细边框可读 |
| 可访问性 | primary/muted/status/focus 的对比度可读；reduced-motion 生效；键盘 focus 没有被主题覆盖掉 |

## 风险与处理

| 风险 | 现场原因 | 处理 |
| --- | --- | --- |
| 首帧闪烁 | `main.tsx:5` 通过模块加载 CSS；lazy `MainApp`/`Suspense` 还会有 fallback；当前 `--ow-bg` 未定义 | `index.html` head bootstrap + `main.tsx` 同步兜底；先定义 `--ow-bg`；loading 也只消费 token |
| 两窗口状态漂移 | `MainApp`/`MenubarPopover` 是不同 React 树和 webview | main 是唯一 writer；app-wide native `setTheme` + 每窗 `onThemeChanged` + storage/matchMedia fallback；不做第二套 picker |
| 硬编码漏网 | 盘点到 39 个 `mac-app/src` 文件含主题相关硬编码；`CommandRegistry` 还在 JSX style 里写 hex；`UsageBrowser` 写 gradient rgba | 先共用 CSS，再按页面分批；token contract + source scan + 逐页视觉矩阵；新 UI 禁止白色 utility |
| 对比度/状态混淆 | 暗色中沿用浅色 `slate-*`/soft 状态会变灰或发光；muted、disabled、warning/error 容易混淆 | 每个状态成对定义 fg/bg；focus 使用专门 token；以安装态截图和对比度审查校准，不能只看颜色反转 |
| prefers-reduced-motion | 现有 `transition-all`、`transition-transform`、`animate-spin` 分布在 App、TaskBoard、表单等 | 主题 transition 只声明颜色/背景/边框/阴影；加 reduce-motion media 覆盖；不做整窗 opacity 动画 |
| 透明 menubar | Rust `.transparent(true)`、透明背景，React effect 清理 html/body/root；直接 `bg-white` 会露出亮面或破坏层次 | 外壳继续 transparent，实际 panel/header/nav/main/footer 使用 `--ow-surface*`；在已安装 popover 上检查圆角边缘和 hide/show/warmup |
| 原生 API/权限失败 | dev/source mode 没有 Tauri internals；现有 `core:window:default` 未授权 `set_theme` | native 调用 try/catch，不阻塞 DOM；只增 `core:window:allow-set-theme`；跑 `tsc`、Tauri build 和安装态 API smoke |
| 存储损坏/不同 webview partition | localStorage 可能缺失、非法或读取异常；跨窗口 storage 行为需安装态确认 | 合法值校验和 system fallback；Tauri `app:theme-changed` 作为实时通道，storage 作为持久化/启动兜底；实际安装包验证首次选择/重启/新开 menubar |
| 主题迁移借机改布局 | 页面有复杂 grid、sticky scroll、popover 尺寸和移动分支 | 修改清单限定颜色/材质/ring/status；测试保留现有结构契约；视觉验收对照 `docs/screenshots/dashboard.png` 和现有 popover 设计 |

## 推荐交付边界

本研究只应驱动主题相关实现。不要顺手修改 Provider、通知、Session 数据流，不把主题偏好写入用户 config，不引入主题库，不修改 `tailwind.config.js`，也不现在修改 `docs/UI-THEME.md` 或其他正式文档。安装包验证在获得用户明确许可前保持未验证状态。
