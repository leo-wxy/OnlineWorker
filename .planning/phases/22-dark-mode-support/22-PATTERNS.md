# Phase 22 代码模式映射

供 planner 直接复用的最近 analog。主题只增加偏好、DOM/native 同步和颜色材质迁移；不新增主题库、`ThemeProvider` 或组件库（`22-RESEARCH.md:44-57,324-326`）。

## `mac-app/src/utils/theme.ts`：偏好状态与持久化

- **最近 analog：** `mac-app/src/i18n/index.tsx:13,31-47`；`mac-app/src/pages/SetupWizard.tsx:24,31-36,61,128-136`。
- **必须复用：** 用模块常量保存 key；用 `typeof window === "undefined"` 守卫读取；非法/缺失值走默认值；读取初始化函数配合惰性 state；变更后在 effect/显式 setter 中写回 `window.localStorage`。主题应分离 `ThemePreference (system|light|dark)` 与 `ResolvedTheme (light|dark)`，共享入口导出 `readThemePreference`、`resolveTheme`、`applyResolvedTheme`、`setThemePreference`、`installThemeSync`（`22-RESEARCH.md:35-57`）。
- **不该复制：** 不要把主题塞进 `I18nContext`（`mac-app/src/MainApp.tsx:1-9` 只给主窗口包 provider，menubar 是另一棵 React 树）；不要写入 `config.yaml`/Rust 业务状态，不要让 localStorage、native IPC 失败阻塞 DOM 主题；不要创建 React `ThemeProvider` 或状态管理依赖。

## `mac-app/index.html` + `mac-app/src/main.tsx`：首帧与 main/menubar 共入口

- **最近 analog：** `mac-app/index.html:1-11` 的单一 module script；`mac-app/src/main.tsx:3-15,26-36` 的 `getCurrentWindow().label` 分流、menubar 直渲染、主 App lazy load 和唯一 `ReactDOM.createRoot`；`mac-app/tests/bundleSplitting.test.mjs:22-32` 对该边界做 source contract。
- **必须复用：** 在 `index.html` 的 module script 之前放极小同步 bootstrap：读取同一主题 key/合法值、按 `matchMedia("(prefers-color-scheme: dark)")` 解析，并同步写 `document.documentElement.dataset.owTheme`；`main.tsx` 在构造 `content`/`createRoot` 前调用同一模块的初始化与 `installThemeSync`，保留 label 分流和单一 root（`22-RESEARCH.md:61-80,184-196`）。
- **不该复制：** 不要在 `App` 与 `MenubarPopover` 各写一套初始化/监听/偏好 writer；不要让 bootstrap 引入模块、异步 Tauri 调用或业务逻辑；不要改变 `MainApp` 的 I18n 边界或 lazy/suspense 页面分发。

## `mac-app/src/utils/theme.ts`、`main.tsx`：Tauri event/window API 与 cleanup

- **最近 analog：** `mac-app/src/App.tsx:102-151` 的 `listen<T>`、异步拿到 unlisten、卸载 cleanup、非 Tauri catch；`mac-app/src/components/menubar-popover/MenubarPopover.tsx:112-134,180-203` 的 `disposed` 保护和 `getCurrentWindow().onFocusChanged` 生命周期；拖拽 native API 的 try/catch 在 `mac-app/src/App.tsx:222-233`。
- **必须复用：** 每个 webview 安装同一 sync；监听 `getCurrentWindow().onThemeChanged`、`matchMedia` change、Tauri `app:theme-changed`，返回 cleanup；异步 `onThemeChanged(...).then(unlisten)` 要处理窗口销毁竞态。显式 `light/dark` 不被系统事件覆盖，`system` 才跟随 native payload；先同步 DOM/偏好，再尝试 `setTheme(null|"light"|"dark")` 和广播（`22-RESEARCH.md:67-80,82-98`）。
- **不该复制：** 不要用业务 `listen`/`invoke` 去同步两个窗口，不要依赖 `storage` 事件作为 WKWebView 唯一实时通道；不要遗漏 `disposed`/cleanup，也不要让 native API 异常覆盖已经生效的 DOM 结果。

## `mac-app/src-tauri/capabilities/default.json`：最小 capability

- **最近 analog：** 当前 capability 已同时覆盖两窗口并复用默认权限：`mac-app/src-tauri/capabilities/default.json:3-11`；schema 已单独声明 `core:window:allow-set-theme`：`mac-app/src-tauri/gen/schemas/desktop-schema.json:1829-1834`，而 `core:window:default` 已含 `allow-theme`：`1440-1443`。
- **必须复用：** 继续使用 `getCurrentWindow().setTheme`/`onThemeChanged`；权限列表只增加 `"core:window:allow-set-theme"`，保留 `core:event:default` 和现有 windows 列表（`22-RESEARCH.md:82-98`）。
- **不该复制：** 不要申请 `core:app:allow-set-app-theme`（schema 仅说明其存在于 `462-465`），不要改 capability scope、窗口名或引入新插件。该文件是根 capability 变更：实施前必须说明对 `main` 与 `menubar-popover` 两窗口权限面的影响和回滚面；获明确许可后才做打包/安装/重启及安装态 native/theme 验证，源级测试或 `open` 不能替代安装态结论（`22-VALIDATION.md:12,67-76`；`AGENTS.md:Packaging/Validation`）。

## `mac-app/src/index.css`：语义 token 与既有 `ow-*` 表面

- **最近 analog：** `mac-app/src/index.css:5-27` 的 `--ow-*` 变量；`68-158` 的 app shell、sidebar、page frame、toolbar、segment 与 button；`216-271` 的 modal、log 与可交互表面。
- **必须复用：** 继续让 `index.css` 成为颜色真相源，保留现有 `--ow-sidebar`、`--ow-panel`、状态色和 `.ow-*` 类作为兼容消费面；新增 `--ow-bg`、surface/input/code/text/focus/overlay/shadow 等语义 token，并在 `:root[data-ow-theme="light"]`/`dark` 成对定义。状态、滚动条、modal、日志与过渡规则集中在此，不给各页面复制主题分支（`22-RESEARCH.md:100-131`）。
- **不该复制：** 不要修改 `tailwind.config.js`、启用 Tailwind dark variant 或新增主题依赖；不要为单一页面建立专属 token，也不要用主题迁移重排 DOM/grid/尺寸。约 150ms 只覆盖颜色相关属性，`prefers-reduced-motion` 下关闭或缩短。

## `mac-app/src/App.tsx`：语言旁的分段选择器

- **最近 analog：** `mac-app/src/App.tsx:330-375` 的语言 segment、展开侧栏和收起分支；共享 segment 外观见 `mac-app/src/index.css:128-145`。
- **必须复用：** 在展开侧栏的语言控件附近增加 `System / Light / Dark` 三项，复用 segment 语义类与按钮可访问名称；App 只保存偏好显示值并调用 shared setter。收起分支不渲染主题选择器，不新增 Settings tab 或顶层导航。
- **不该复制：** 不要让 App 自己实现 matchMedia/native listener；不要把 resolved theme 当业务 state 向每页传 props，也不要复制第二套颜色 utility。

## `MenubarPopover`：透明外壳与现有信息结构

- **最近 analog：** `mac-app/src/components/menubar-popover/MenubarPopover.tsx:58-85` 的透明 html/body/root 生命周期、`261-370` 的 header/nav/footer、`398-736` 的 Overview/Provider/Usage/session 内容；provider/status 映射集中在 `mac-app/src/utils/menubarPopover.ts:38-125`。
- **必须复用：** 保留透明外壳、约 420px 紧凑布局、现有 tabs/rows/底部入口和 provider 选择逻辑，只把实际 panel、文字、边框和状态类换成全局 token；menubar 由 `main.tsx` 的 shared sync 自动消费主题。
- **不该复制：** 不要新增 menubar 主题入口、卡片、指标或操作；不要给 html/body/root 套不透明主题背景；不要创建 menubar 专属偏好 writer 或 token 表。

## `mac-app/tests/*.test.mjs`：源级契约与文档契约

- **最近 analog：** `mac-app/tests/appShell.test.mjs:1-23`、`menubarPopover.test.mjs:1-29`、`bundleSplitting.test.mjs:22-32` 使用 Node `node:test`、`readFileSync` 和窄正则断言现有源码边界。
- **必须复用：** 新建 `theme.test.mjs` 验证偏好/首帧/API/事件/cleanup source contract；新建 `themeContract.test.mjs` 读取 `index.css` 与 `docs/UI-THEME.md`，核对两主题 token、旧 alias 和禁止硬编码规则；扩展现有 App/menubar 测试保住布局与入口。
- **不该复制：** 不要安装 Jest/Vitest、做脆弱整文件快照或把所有颜色字面量一刀切判错；允许例外必须精确到语义与文件，不能整目录忽略。

## `docs/UI-THEME.md`：稳定规范与最小索引

- **最近 analog：** `docs/README.md:1-35` 是公共开发资料索引；`CONTRIBUTING.md:43-68` 集中列验证命令；日期化 menubar 草案 `docs/superpowers/specs/2026-07-07-menubar-popover-design.md` 只作为已有信息结构约束。
- **必须复用：** 新建单一稳定规范 `docs/UI-THEME.md`，写 preference/resolved model、token、组件消费、硬编码禁令、可访问性、menubar 透明例外、增量扩展与验证；只在 `docs/README.md` 增加索引，在 `CONTRIBUTING.md` 加一条入口链接。
- **不该复制：** 不要把 token 表重复写入产品 README 或 CONTRIBUTING，不要创建多份日期化主题规范；实现 token 与文档必须由 `themeContract.test.mjs` 保持一致。
