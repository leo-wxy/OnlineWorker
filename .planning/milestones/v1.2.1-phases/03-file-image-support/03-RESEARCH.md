# Phase 3: File and Image Support - Research

**Researched:** 2026-05-13
**Domain:** Telegram + desktop attachment routing across provider/plugin boundaries
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- 第一版同时覆盖 Telegram 与桌面端
- 同时支持图片和通用文件
- 附件必须进入现有 provider/plugin 工作流
- 不接受只做 UI 假按钮或只做 Telegram 单入口

### the agent's Discretion
- 附件展示密度与 UI 样式
- 单次附件数量限制
- 下载目录与命名细节
- 失败恢复交互

### Deferred Ideas (OUT OF SCOPE)
- 多附件管理器
- 拖拽排序和图库式预览
- OCR / 视觉推理能力增强
- 新 provider family

</user_constraints>

<architectural_responsibility_map>
## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Telegram 附件采集与落地 | Python bot | Local storage | 只有 bot 能拿到 Telegram file_id / 下载内容 |
| 桌面端文件选择与发送请求 | React + Tauri command | SessionBrowser shell | 桌面端负责用户交互，不能直接进 provider 解析层 |
| 共享附件消息 contract | Core provider boundary | Tauri / Python adapters | 需要统一描述 text + attachments |
| provider-specific 附件 send 适配 | Provider runtime / adapter | Plugin manifest / descriptor | 不同 provider CLI 对附件输入方式天然不同 |
| packaged-app 验证 | Build/install pipeline | Installed `OnlineWorker.app` | Python sidecar 与桌面端都被改到，必须安装态验证 |

</architectural_responsibility_map>

<research_summary>
## Summary

当前仓库已经具备三个可复用基础，但也有三个明确缺口：

### 已有基础
1. **Telegram thread 路由已经成熟**  
   `bot/handlers/message.py` 已经能按 workspace/thread/topic 路由消息，也已经识别 `photo`。这意味着 Phase 3 不需要重写 Telegram 消息分发，只要把附件采集层接进去。

2. **桌面端已有统一 session 发送入口**  
   `SessionBrowser` 的 `SessionComposer` 已经是发送消息的唯一主要入口，而且 UI 上已经有附件图标，占位已在，只是没有行为。

3. **provider/plugin 边界已经存在**  
   共享层已经通过 `ProviderMessageHooks`、`provider_session_bridge`、Tauri commands 来把运行时差异收在 provider 边界后面。

### 当前缺口
1. **共享消息模型还是纯文本模型**  
   现在无论 Python 还是桌面端，发送核心仍然是 `send_user_message(workspace_id, thread_id, text)`。这意味着附件支持不能只做 UI 或 handler patch，必须先升级共享消息 contract。

2. **contract 只会描述“图片”不会描述“文件”**  
   现在 `ProviderMessageHooks.supports_photo` 和 manifest 的 `photos` 只能表达单一图片布尔能力，无法表达通用文件能力、附件列表或 text+attachments 组合。

3. **Telegram 与桌面端都缺附件物化链路**  
   Telegram 还没有 `document` 下载落地逻辑；桌面端还没有文件选择和路径桥接命令。

**Primary recommendation:** 先在共享层引入 `AttachmentPayload` / `UserMessagePayload` 这类统一消息 contract，再分两波实现：
- 波次 1：Python Telegram 入口 + provider runtime 支持
- 波次 2：桌面端 SessionBrowser 附件入口 + Tauri bridge + 安装态验证

这样做的理由很直接：如果不先升级 contract，后面 Telegram 和桌面端会各自造一套附件结构，最后还是要返工。
</research_summary>

<standard_stack>
## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python Telegram Bot | repo current | Telegram `photo` / `document` 下载与消息接收 | 当前 bot 运行时 |
| React 18 + Tauri 2 | repo current | 桌面端附件入口与 invoke bridge | 当前桌面栈 |
| Python provider adapters | repo current | 附件消息进入 `codex` / `claude` provider 工作流 | 现有运行时边界 |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Rust Tauri commands | repo current | 桌面端路径桥接、session send API 扩展 | 保持本地文件系统与前端解耦 |
| Local filesystem | repo current | Telegram 下载附件与桌面端本地路径引用 | 必需的中间层 |

</standard_stack>

<architecture_patterns>
## Architecture Patterns

### Pattern 1: Unified attachment message payload
**What:** 引入统一的“文本 + 附件列表”消息负载，而不是继续散落 `text` / `has_photo` / `caption`。  
**Why:** Telegram 和桌面端都要复用同一发送语义；provider 侧也需要稳定输入结构。  
**Local fit:** 当前仓库已经有 shared contract / runtime hook 边界，这是自然延伸。

### Pattern 2: Entry-point specific acquisition, shared downstream routing
**What:** Telegram 负责下载 Telegram 附件到本地，桌面端负责选择本地文件；但两者最终都转成统一 attachment payload，再进入 provider runtime。  
**Why:** 入口差异应该停在采集层，不能把差异泄漏到 provider shared UI。

### Pattern 3: Capability declaration in manifest + descriptor
**What:** provider manifest 与 descriptor 要显式声明图片/文件能力，而不是靠共享层硬判断。  
**Why:** 这符合 public plugin boundary，也方便 overlay provider 后续接入。

### Anti-Patterns to Avoid
- 在 React 里直接读取本地文件并把原始路径格式硬编码进 provider-specific 参数
- 让 Telegram handler 直接分支 `if provider == codex`
- 只补 `supports_photo=True`，继续忽略通用文件
- 只改源码态，不做安装态 sidecar 验证

</architecture_patterns>

<dont_hand_roll>
## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| 新的附件消息通道 | 第二套独立发送 API | 升级现有 `send_user_message` 语义/contract | 保持 thread send 入口统一 |
| 桌面端附件页 | 新做独立附件页面 | 复用 `SessionBrowser` composer | 附件本质上是 thread 发送动作 |
| provider 分发 | React 内直接分支 provider | descriptor / runtime hooks / bridge | 避免重新硬编码 provider |

</dont_hand_roll>

<common_pitfalls>
## Common Pitfalls

### Pitfall 1: 只做图片，不做通用文件
**What goes wrong:** UI 和 contract 很快再次重构，因为“图片”和“文件”被拆成两条路径。  
**How to avoid:** 直接用统一 attachment list，类型字段区分 `image` / `file`。

### Pitfall 2: Telegram 只传 file_id，不做本地落地
**What goes wrong:** provider runtime 无法稳定消费 Telegram 临时引用，安装态也难验证。  
**How to avoid:** 下载到应用数据目录，再把本地受控引用送下游。

### Pitfall 3: 桌面端只做按钮，不改发送 contract
**What goes wrong:** 最终附件仍然进不了 provider workflow，只能停在前端占位。  
**How to avoid:** Phase 3 第一计划先改共享 contract 和 runtime send path。

### Pitfall 4: 忘记安装态验证
**What goes wrong:** Python sidecar / packaged app 路径在源码态通过，但安装后失效。  
**How to avoid:** Phase 3 第二计划必须包含 `bash scripts/build.sh` + 安装态覆盖启动验证。

</common_pitfalls>

<verification_strategy>
## Verification Strategy

- Python 定向测试：
  - Telegram `photo` / `document` 路由
  - provider message contract 升级后的 handler 行为
  - 不支持附件的 provider fallback

- 前端 / Tauri 定向测试：
  - `SessionComposer` 附件入口 wiring
  - Tauri command 的本地文件发送桥接
  - 共享类型与 invoke contract 编译通过

- 安装态验证：
  - 重新构建 sidecar 与 DMG
  - 覆盖安装 `/Applications/OnlineWorker.app`
  - 启动安装态，验证 Telegram 和桌面端都能触发附件工作流

</verification_strategy>

---

*Phase: 03-file-image-support*
*Research completed: 2026-05-13*
