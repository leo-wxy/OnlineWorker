---
phase: 23
slug: plugin-owned-codex-account-and-session-asset-management
status: approved
shadcn_initialized: false
preset: none
created: 2026-08-17
---

# Phase 23 — UI Design Contract

> Codex 插件自包的账号凭据转移与本地会话资产管理。Cockpit Tools 只提供信息架构和操作流程参考；OnlineWorker 现有主题、组件和无障碍规则是视觉权威。

## Design System

| Property | Value |
|----------|-------|
| Tool | 现有 Tailwind CSS、OnlineWorker `ow-*` utilities 与插件自带语义 CSS |
| Preset | 现有 installed-app light / dark / system 主题 |
| Component library | 无新增库；复用现有 React/HTML 组件 |
| Icon library | 现有 inline SVG + `currentColor` 模式 |
| Font | `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif` |
| Ownership | Host 只负责通用入口、发现、selector shell 和错误边界；插件负责全部 Codex 文案、数据、操作、校验和内容 |

禁止新增依赖、字体、全局主题 token、host 中的 Codex 特判、API 中转/网关、账号池或后台配额轮询。插件 CSS 只能消费现有语义 token，不修改 host 的 Tailwind 扫描范围。

## Information Architecture

```text
OnlineWorker sidebar
└── 账号                              至少一个 account-capable 插件启用时才显示
    └── Generic plugin selector        每个已发现插件一个 selector
        └── Codex plugin
            ├── 账号
            │   ├── 账号总览
            │   ├── 对齐的账号列表与官方额度窗口
            │   └── 添加账号弹窗
            └── 会话资产
                ├── 近 30 天 Token / 成本摘要
                ├── 标题搜索与选中范围批量操作
                └── 响应式工程目录卡片
                    └── 选择会话弹窗：搜索 / 全选当前结果 / 逐条选择
```

- 没有 account-capable 插件时，侧边栏不显示“账号”。
- Host 只渲染插件声明的 label/icon/schema，不按 `provider_id` 分支。
- Selector loading 使用 `正在加载账号插件…`，loading 时禁用 selector mutation 并通过 `aria-live="polite"` 通知。
- 某个插件失败时仅该 selector 显示“加载失败 / 重试 / 查看诊断”，其他 selector 仍可用。
- OnlineWorker bot、provider runtime、owner bridge、Task Board、Usage、notification 或 Codex app-server 停止时，页面仍可用。
- 该页不复用或扩展实时 Sessions/Usage 页。Codex 内部可用“账号 / 会话资产”分段控件。
- Phase 23 不提供 copy-to-instance、跨实例同步、多个命名 Codex Home，也不实现 Claude/Codemaker 账号界面；这些不显示占位控件。

## Spacing Scale

| Token | Value | Usage |
|-------|-------|-------|
| xs | 4px | icon/text gap、badge padding |
| sm | 8px | 行内控件、metadata gap |
| md | 12px | 紧凑行/卡片 padding |
| lg | 16px | 页面/分区 padding、toolbar gap |
| xl | 24px | 卡片/弹窗分区间距 |
| 2xl | 32px | 页面主分区 |

Exceptions: 1px border、现有 3px 侧边栏活动指示器和原生 focus ring。

## Typography

| Role | Size | Weight | Line Height |
|------|------|--------|-------------|
| Body | 14px | 400 | 1.45 |
| Label / metadata | 12px | 600 / 500 | 1.4 |
| Row title | 14px | 700 | 1.4 |
| Page heading | 24px | 800 | 1.2 |
| Summary value | 24px | 800 | 1.2 |

- 标题最多两行；Session id、文件名和路径使用现有等宽处理与安全截断。
- 30 天摘要保持紧凑，不使用配额/大盘风格的超大数字。

## Color

只使用现有语义 token：

| Role | Token | Usage |
|------|-------|-------|
| Canvas/shell | `--ow-canvas`, `--ow-shell`, `--ow-sidebar` | 页面和导航背景 |
| Surface | `--ow-panel`, `--ow-panel-soft`, `--ow-panel-elevated` | 卡片、列表、弹窗 |
| Toolbar/input | `--ow-toolbar`, `--ow-input` | 搜索和操作栏 |
| Structure | `--ow-line`, `--ow-line-soft` | 边框/分割线 |
| Text | `--ow-text`, `--ow-muted`, `--ow-subtle` | 主文字和辅助信息 |
| Focus/selection | `--ow-blue`, `--ow-blue-soft`, `--ow-focus` | 选中、focus、单一主操作 |
| Success | `--ow-green`, `--ow-green-soft` | import/apply/export/restore 成功 |
| Warning | `--ow-amber`, `--ow-amber-soft`, `--ow-warning-text` | 外部/未托管、部分结果 |
| Error | `--ow-red`, `--ow-red-soft`, `--ow-error-text` | 校验和操作失败 |

Accent 只用于选中/focus/每个 surface 的单一主操作。禁止 provider 颜色铺满卡片、硬编码 hex/RGBA、新增或硬编码渐变、彩色阴影和纯颜色状态；允许复用现有语义渐变 token。

## Account Overview

- Eyebrow / heading: `账号管理`
- Description: `管理本地 AI 服务账号。导入后需手动应用到对应客户端。`
- Primary CTA: `添加账号`
- Codex plugin selector label: `Codex`

账号列表只显示：selection checkbox、稳定身份、`当前账号` / `未应用`、来源（新入口为 `OAuth` / `Token / JSON`；历史记录可显示 `API Key` / `文件导入`）、外部状态（`外部修改` / `未托管`）、官方返回的 plan/额度窗口，以及 `应用`/`重新应用`、`刷新额度`和 `导出`。桌面使用响应式卡片网格；每张卡片是一个 16px 圆角的单层 surface，内部按“身份与状态 → 额度 → 底部操作”排列，metadata 使用紧凑行，额度以 hairline 分隔，不再嵌套独立的 metadata/quota 卡片。当前账号只使用蓝色内侧边和轻量背景强调，不使用额外彩色外圈。页面提供 `全选当前结果`、`清除选择`、`已选择 {count} 项`和 `导出选中`；无选中时用 native `disabled`。

账号工具栏使用 16px 圆角的紧凑 surface：账号统计、全选/选择数和批量操作共享同一对齐基线，空间不足时自然换行，不让批量按钮孤立漂浮。

账号首屏允许从 versioned local cache 读取上述列表行所需的脱敏字段；命中时立即渲染，随后后台执行 `accounts.list` 覆盖校准。缓存只按显式白名单重建对象，不保存 callback、表单输入、native path、credential/token 或 backend 未知字段。后台刷新失败时保留已有缓存行并显示错误。

| State | Copy and behavior |
|-------|-------------------|
| Cached | 立即显示脱敏账号行；后台校准不清空已有行，真实返回后覆盖缓存 |
| Loading | `正在加载账号…`；mutation 禁用，不用旧响应覆盖新状态 |
| Empty | 左侧为 `账号库为空` / `添加第一个账号` / `通过 OAuth 或 Token / JSON 导入凭据。导入后由你决定何时应用，不会自动切换当前账号。` / `添加账号`；右侧以 `01 安全导入`、`02 手动应用`解释两步流程。不得使用大面积居中占位卡或装饰插画。 |
| External matched | `检测到外部凭据文件已匹配此账号。`；不自动应用 |
| External unmanaged | `检测到未托管的当前账号。请导入后决定是否加入账号库。` |
| Plugin error | `账号功能加载失败。请重试，或查看诊断。` + `重试` + `查看诊断` |
| Import success | `账号已导入。需要使用时，请点击“应用”。`；current account 不变 |
| Apply success | `账号已应用到当前 Codex Home。` |
| Apply failure | `应用失败，已恢复之前的凭据。`；current account 不变 |
| Quota idle | `尚未刷新额度`；仅用户点击时访问官方 Codex usage endpoint |
| Quota loading | `正在刷新额度…`；只禁用该账号的刷新操作 |
| Quota success | 显示官方 plan、额度百分比和重置时间；不推导官方响应中不存在的值 |
| Quota unavailable | `额度暂不可用` + 精简错误；保留上次成功结果，不伪造 `0` |

## Add Account Modal

复用 `ow-modal-backdrop` / `ow-modal-panel` 及现有 dialog focus 模式。

- Title: `添加账号`
- Description: `选择一种方式，将凭据安全地加入本地账号库。`
- 两个 tab 的精确文案：`OAuth`、`Token / JSON`。
- 共通状态：`正在校验…`、`正在导入账号…`；执行期间禁用所有 mutation 控件；错误保留用户输入。

### OAuth tab

- 启动授权必须使用 PKCE + `state`；自动本地回调和手动 callback URL 都必须验证 `state`。
- Idle CTA: `在浏览器中继续`
- Hint: `将打开系统浏览器完成授权。授权完成后会自动接收本地回调。`
- Waiting: `正在等待浏览器授权…` / `等待本地回调…`；开始监听、打开浏览器、等待回调和交换凭据期间始终允许 `取消` 或关闭弹窗。
- 取消必须绑定当前 OAuth operation；关闭弹窗或离开账号页面后，旧 operation 不得写入账号，也不得删除后来启动的新 operation。
- Manual fallback: `没有收到本地回调？`；field `回调 URL`；CTA `使用回调 URL`。
- Success: `授权成功，账号已导入。需要使用时，请点击“应用”。`
- Errors: `授权已取消。`、`没有收到本地回调。请粘贴回调 URL，或重新开始授权。`、`回调状态无法验证。请重新开始授权。`、`授权失败：{reason}`；retry `重新授权`。
- 不嵌入登录 WebView。

### Localhost callback confirmation

- 浏览器回调页只确认本地回调已被 OnlineWorker 接收，不承诺账号已经导入；最终结果回到应用内查看。
- 固定信息层级：`授权回调已接收`、`请返回 OnlineWorker 查看结果`、`关闭页面`；不得宣称授权或账号导入已经成功。
- 页面提供可用的 `关闭页面`；浏览器不允许脚本关闭时显示可理解的手动关闭提示。
- 页面保持 provider-neutral，不显示 Codex 标题，不回显 query、code、state、token 或错误详情，并在加载后从地址栏清除 query。

### Token / JSON tab

- Help: `粘贴完整 Token 或账号 JSON。仅在本地完成结构和身份校验。`
- CTA: `导入账号`
- Invalid shape: `账号 JSON 格式不受支持。请检查版本和必需字段。`
- Invalid identity: `无法解析账号身份。请修正后重试。`
- 不执行登录、refresh 或网络验证。

## Apply and Account Export

`Import` 与 `Apply` 在视觉和行为上始终分离；import success 不得暗示 apply success。

- Apply confirmation: `应用此账号？这只会更新当前 Codex 凭据文件，不会停止、重启或重新连接任何进程。`
- Apply states: `应用`、`正在应用…`、`重新应用`、`请先导入账号`。当前账号允许显式重新投影凭据，按钮不得因“已经是当前账号”而永久禁用。
- Apply failure: `应用失败，已恢复之前的凭据；当前账号未改变。`
- Export actions: 卡片单账号 `导出`、选择栏 `导出选中`；两者都显示 confirmation `导出的文件包含完整凭据，请仅保存到受信任的位置。`
- Export 使用 native save dialog；states `正在导出…`、`账号已导出：{filename}`、`导出失败：{reason}`；save dialog cancel 不产生成功/错误状态。

## Session Asset Page

```text
会话资产
├── 近 30 天：Token 总量 / 估算成本
├── Toolbar：标题搜索 / 导入 ZIP / 导出选中 / 修复可见性 / 选中范围操作
└── Workdir cards：cwd title / conversation count / latest date / recent conversations
    └── Conversation picker dialog：search / visible-result select-all / checkbox rows
```

### 30-day Summary

- Heading: `近 30 天`；values: `Token 总量`、`估算成本`。
- Caption: `根据当前有效 Codex Home 的本地文件计算，不读取 OnlineWorker 用量投影。`
- States: `正在读取本地会话数据…`、`近期 30 天没有可统计的本地数据。`、`成本数据不可用`、`无法读取本地会话数据。请重试。`
- 成本不可用时不伪造 `0`。

### Search, Selection, and Rows

- Search label / placeholder: `按标题搜索会话` / `搜索会话标题或工作目录`；当前会话和废纸篓都同时匹配 conversation title、`cwd` 和 session id。
- Empty search: `没有匹配的会话或工作目录。`；selection: `已选择 {count} 项`。
- Batch actions: `全选当前结果`、`清除选择`、`导出选中`、`移到废纸篓`。无选中时用 native `disabled`。
- 批量操作只作用于显式选中/当前可见结果，不修改隐藏集合。
- 一级列表按 effective `cwd`/project 分组为响应式卡片；卡片显示目录名、完整路径、conversation 数量、最后活动时间和最多两条最近会话，避免把每条对话一级平铺。所有卡片高度和底部 `选择会话` 操作保持一致。
- `选择会话` 使用 native dialog。弹窗内可按 title/session id 搜索、全选当前可见结果或逐条勾选；取消不改变页面选择，确认只替换当前工程的选择并保留其他工程的已选会话。conversation row 使用 label + sibling native checkbox，不嵌套其他交互控件。
- 后台刷新保留已渲染行，不用全屏 loading 清空列表。

### ZIP Import / Export

- Import CTA: `导入 ZIP`；states `尚未选择 ZIP 文件。`、`正在校验 ZIP…`、`正在导入会话资产…`、`会话资产已导入。`
- Partial: `已导入 {ok} 项，跳过 {skipped} 项，拒绝 {rejected} 项。`
- Conflict: `检测到冲突的 Session，未静默覆盖；结果已逐项列出。`
- Integrity/version: `ZIP 清单或校验和无效，未导入受影响的 Session。` / `ZIP 格式或版本不受支持，请检查导出来源。`
- Export CTA: `导出选中`；states `正在准备 ZIP…`、`会话资产已导出：{filename}`、`导出失败：{reason}`；cancel 不显示成功/错误。

### Reversible Trash / Restore

- Segment: `当前会话` / `废纸篓`；actions `移到废纸篓` / `恢复`。
- Confirmation: `移到废纸篓？会话历史不会被永久删除，之后可以恢复。`
- States: `正在移到废纸篓…`、`已移到废纸篓，可在废纸篓中恢复。`、`正在恢复…`、`会话已恢复。`
- Errors: `无法恢复：废纸篓清单不完整。` / `操作失败，未修改会话历史。`
- Phase 23 不提供永久删除入口。

### Visibility Repair

- CTA: `修复可见性`；explanation `仅修复本地 Codex 会话索引的可见性，不会删除会话内容。`
- Confirmation: `开始修复可见性？`
- States: `正在修复可见性…`、`可见性已修复：恢复 {restored} 项，保留 {kept} 项，未修改 {unchanged} 项。`、`未发现需要修复的会话。`、`可见性修复失败，未修改会话文件。`
- 操作仅在 Codex 插件内，不发布 EventBus/session/notification 事件。

## Error, Retry, and Diagnostics

所有插件边界失败都必须包含：简短原因、可重试时的 `重试`、有价值时的 `查看诊断`，且不包含凭据、token 片段或会话原文。Apply、export、trash、restore 和 visibility repair 的可重试失败必须显示独立 `重试` 控件；不可重试错误必须明确说明原因与可执行的下一步。Save dialog cancel 保持静默。Host 通用文案：

- `此账号插件暂时不可用。`
- `插件加载失败不会影响其他账号插件。`

不通过 provider runtime readiness、owner bridge、Task Board 或实时 Sessions 表达这些错误。

## Responsive Contract

使用现有 Tailwind 断点：`sm=640`、`md=768`、`lg=1024`、`xl=1280`。

- `>=1100`: 账号与会话工程使用 `auto-fit` 卡片网格；空间允许时并排显示多张独立卡片，账号卡固定“身份 / 额度 / 操作”顺序且操作贴底；空态使用左右分栏；30 天摘要 2 列；toolbar 单行优先。
- `768–1099`: 卡片网格按可用宽度自动降为单列；账号空态降为上下结构；卡内信息和操作自然换行；会话标题与操作不溢出。
- `<768`: 每行一张账号或会话工程卡片，卡内信息单列；toolbar 换行；modal footer 按钮全宽堆叠。
- `<640`: modal `p-4`，页面复用现有 `p-5`，账号行 `p-4`；身份、额度、actions 单列，不定宽。
- 侧边栏收起为 84px 时保留“账号”icon 和 `title`/`aria-label`；展开复用 248px。
- 页面不得产生水平滚动。窄屏 session detail 复用现有 list/detail 切换并显示 `返回列表`。

## Accessibility and Keyboard

- 侧边栏入口使用 native button，accessible name `账号`。
- Provider selector 使用 `role="tablist"` 或等价 labelled group；选中项暴露 `aria-selected`。
- Modal 使用 `role="dialog"`、`aria-modal="true"`、关联 title/description、Escape 关闭、初始 focus 和 focus restore。
- 所有 input 有可见 label 或 `aria-label`；Token / JSON 输入不持久化。
- Add-account tabs 可键盘激活；focus ring 使用 `--ow-focus`。
- Session 工程卡使用原生 `button` 打开关联标题的 native dialog；弹窗内 checkbox 用 Space 选中，Escape/取消关闭且不提交，确认后通过 `aria-live` 更新选择数量。
- Async status 用 `aria-live="polite"`；需要立即注意的错误用 `role="alert"`。
- 状态同时有文字/icon，不只靠颜色。禁用操作使用 native `disabled`，不接受 pointer/keyboard mutation。
- 遵守 `prefers-reduced-motion: reduce`，不新增 transform/opacity transition。

## Acceptance State Matrix

| Surface | State | Acceptance |
|---------|-------|------------|
| Sidebar | no plugin / discovered | 入口缺席 / 恰好一个动态“账号”入口 |
| Plugin selector | loading / error | `正在加载账号插件…` + disabled + `aria-live`；host 无 Codex 特判；错误隔离 + `重试` + `查看诊断` |
| Account overview | cached / loading / empty / loaded | 脱敏缓存先显示并后台校准；空态提供导入/应用两步引导；checkbox + selection count + 全选/清除；单层卡片只有身份/current/source/plan/quota/`应用`/`刷新额度`/`导出`，无嵌套 framed metadata/quota 卡 |
| Add modal | idle | `OAuth`、`Token / JSON` 两个精确 tab；无嵌入 WebView |
| OAuth | waiting / fallback / callback confirmation | 系统浏览器、全阶段可取消、callback status、manual URL fallback；localhost 页只确认回调并返回应用查看最终结果 |
| Import | success / invalid | 账号库更新但 current 不变；错误保留输入 |
| Apply | success / failure | 不重启/重连；失败原子回滚 |
| Quota refresh | idle / loading / success / unavailable | 仅显式刷新官方 usage endpoint；保留上次结果；无后台轮询或账号池逻辑 |
| Account export | cancel / success | cancel 安静；完整凭据不出现在列表 |
| Session page | bot stopped | 仍从当前 Codex Home 读本地文件 |
| 30-day summary | success / empty / error | 只用本地数据；不伪造成本 `0` |
| Session projects | card / picker open / picker confirmed | 一级只显示 cwd/project 卡片；底部按钮打开可搜索、全选和逐条选择的 dialog；取消不提交，确认保留其他工程选择 |
| Search/batch | no match / no selection | title/cwd/session id 均可匹配；明确 empty；无选中时 scoped actions disabled |
| ZIP import | conflict / integrity/version error | 不静默覆盖；逐项结果；受影响项不写入 |
| Trash/restore | success / error | manifest-backed 可逆；无永久删除 |
| Visibility repair | success / no-op / error | 计数/no-op；无 EventBus/session/notification 副作用 |
| Responsive | `<1024` | 堆叠或 list/detail；无 page horizontal overflow |
| Keyboard/theme | all states | focus order、Escape、Enter/Space、focus restore；light/dark/system 仅用语义 token |

## Registry Safety

| Registry | Blocks Used | Safety Gate |
|----------|-------------|-------------|
| shadcn / third-party | none | 不适用；不新增 registry block 或 UI 依赖 |

## Checker Sign-Off

- [x] Dimension 1 Copywriting: PASS
- [x] Dimension 2 Visuals: PASS
- [x] Dimension 3 Color: PASS
- [x] Dimension 4 Typography: PASS
- [x] Dimension 5 Spacing: PASS
- [x] Dimension 6 Registry Safety: PASS

**Approval:** approved 2026-08-17
