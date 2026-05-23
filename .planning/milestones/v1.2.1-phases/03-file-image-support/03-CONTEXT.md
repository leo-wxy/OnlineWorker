# Phase 3: File and Image Support - Context

**Gathered:** 2026-05-13
**Status:** Ready for planning

<domain>
## Phase Boundary

为 OnlineWorker 增加一等公民的附件支持：**Telegram 入口**与**桌面端入口**都要支持上传**图片**与**通用文件**，并且这些附件必须进入现有 provider/plugin 工作流，而不是停留在 UI 假按钮或 Telegram 原始消息层。

本 phase 的范围覆盖：
- Telegram thread 消息里的图片与通用文件接收、落地、转发
- 桌面端 session/thread 发送入口的文件/图片选择与发送
- 共享附件 contract、provider message hooks / runtime 适配
- builtin `codex` / `claude` 在现有公共边界下的第一版附件接入

本 phase 不覆盖：
- 新增 builtin provider family
- 浏览器上传或 SaaS 托管入口
- 富媒体画廊、缩略图墙、批量拖拽管理等重 UI 功能
- provider 内部对附件内容的高级理解能力扩展（例如 OCR、视觉推理策略选择）

</domain>

<decisions>
## Implementation Decisions

### Scope and user-facing behavior
- **D-01:** 第一版同时覆盖 Telegram 与桌面端，两边都支持图片和通用文件，不做“先 Telegram、后桌面”或“只做图片”的缩范围。
- **D-02:** 附件支持是 thread/workspace 工作流的一部分，不能绕开现有 provider/plugin routing。
- **D-03:** 用户发送附件时，允许同时附带文本说明；附件与文本需要以同一轮消息语义进入 provider。

### Boundary and architecture
- **D-04:** 共享 contract 必须从当前“纯文本 + has_photo”提升为通用 attachment message contract，不能继续靠零散布尔位硬撑。
- **D-05:** provider-specific 附件转换逻辑保持在 provider/runtime 边界后面，不把 provider 私有参数格式扩散到 Telegram handler 或 React 页面。
- **D-06:** Telegram 入口与桌面端入口都只负责采集附件、存储引用和触发发送；真正的 provider send 仍通过现有 adapter / owner bridge / runtime hooks 执行。

### Data handling
- **D-07:** Telegram 附件需要先下载到本地受控目录，再把本地文件引用交给后续 provider 流程；不能依赖 Telegram 临时 file_id 作为长期输入。
- **D-08:** 桌面端附件第一版使用本地文件路径选择，不做远程 URL 导入。
- **D-09:** 图片与通用文件要在共享数据模型里显式区分，不能继续只保留 `supports_photo` / `photos` 这种单能力位。

### Builtin providers
- **D-10:** `codex` 与 `claude` 都纳入第一版范围；如果某一侧底层 CLI 无法原生携带二进制附件，需要通过既有工作流允许的文本引用 / 文件路径上下文方式接入，但这种差异必须留在 provider 层。
- **D-11:** builtin provider manifest 与 descriptor 需要公开声明附件能力，避免共享层靠 runtime id 猜测。

### the agent's Discretion
- 附件在桌面端 UI 中的具体展示样式
- 单次消息允许的附件数量上限
- Telegram 下载目录与文件命名细节
- 附件发送失败时的文案和恢复交互

</decisions>

<specifics>
## Specific Ideas

- 用户明确要求：
  - “都做”——Telegram 和桌面端都要支持
  - 图片和通用文件都要支持
  - 仍然要按 plugin/provider 边界接入
- 当前现场约束：
  - `bot/handlers/message.py` 已能识别 Telegram `photo`，但还不能处理 `document`
  - provider contract 只有 `supports_photo`，还没有通用 attachment contract
  - `SessionComposer` 里已有附件图标，但现在只是视觉按钮，没有实际发送链路

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Product and roadmap
- `.planning/PROJECT.md`
- `.planning/REQUIREMENTS.md`
- `.planning/ROADMAP.md`
- `.planning/STATE.md`

### Telegram and Python routing
- `bot/handlers/message.py`
- `bot/handlers/thread.py`
- `bot/handlers/common.py`
- `core/state.py`
- `core/storage.py`

### Provider contracts and runtime boundaries
- `core/providers/contracts.py`
- `core/providers/message_runtime.py`
- `core/provider_session_bridge.py`
- `plugins/providers/builtin/codex/plugin.yaml`
- `plugins/providers/builtin/codex/python/provider.py`
- `plugins/providers/builtin/codex/python/runtime.py`
- `plugins/providers/builtin/claude/plugin.yaml`
- `plugins/providers/builtin/claude/python/provider.py`
- `plugins/providers/builtin/claude/python/runtime.py`

### Desktop app surfaces
- `mac-app/src/pages/SessionBrowser.tsx`
- `mac-app/src/components/session-browser/shared.tsx`
- `mac-app/src/components/session-browser/api.ts`
- `mac-app/src/types.ts`
- `mac-app/src-tauri/src/commands/provider_sessions.rs`
- `mac-app/src-tauri/src/lib.rs`

### Validation surface
- `tests/test_handlers.py`
- `tests/test_thread_controls.py`
- `tests/test_slash_router.py`
- `tests/test_config.py`
- `mac-app/tests/appShell.test.mjs`
- `mac-app/tests/usageBrowser.test.mjs`
- `mac-app/package.json`

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `SessionBrowser` 已经是桌面端 thread/session 发送入口，最合适承接附件选择与发送。
- `provider_sessions.rs` 和 `core/provider_session_bridge.py` 已经提供了跨桌面端与 provider runtime 的桥接模式，可继续沿用。
- Telegram `message_handler` 已经有 thread 路由、question/wrapper 等状态机，不需要新建第二套消息分发框架。

### Established Patterns
- 共享桌面端 UI 通过 Tauri `invoke(...)` 调 Rust 命令层；路径、读写与 provider-specific 细节不下放到 React。
- provider-specific 差异通过 descriptor / message hooks / runtime hooks 处理，而不是在共享层硬编码 runtime 分支。
- packaged-app 行为是最终验证对象；涉及 Python sidecar 改动必须重新打包安装验证。

### Integration Gaps
- 当前 `adapter.send_user_message(...)` 仍是纯文本接口，需要提升为支持附件消息负载。
- 当前 contract 只有 `supports_photo` / `photos`，无法描述通用文件能力。
- Telegram 侧还没有 `document` 下载和本地持久化链路。
- 桌面端 composer 的附件图标还没有实际行为。

</code_context>

<deferred>
## Deferred Ideas

- 多附件批量上传和排序
- 图片预览、缩略图墙、拖拽上传
- 非 thread 场景的附件管理面板
- 附件 OCR、图像理解增强、模型自动切换

</deferred>

---

*Phase: 03-file-image-support*
*Context gathered: 2026-05-13*
