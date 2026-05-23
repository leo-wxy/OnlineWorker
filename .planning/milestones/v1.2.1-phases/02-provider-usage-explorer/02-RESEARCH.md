# Phase 2: Provider Usage Explorer - Research

**Researched:** 2026-05-12
**Domain:** Provider usage aggregation and desktop Usage page wiring
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- `Usage` 是一级主导航页面
- 页面参考 `SessionBrowser`
- 顶部支持 `Codex / Claude` 切换
- provider-specific 统计逻辑必须保持在 provider/plugin 边界后面
- 参考 `ryoppippi/ccusage` 的思路，不扩展到别的产品方向

### the agent's Discretion
- 表格列顺序和文案细节
- 是否保留成本列与空值格式
- fallback panel 的文案颗粒度

### Deferred Ideas (OUT OF SCOPE)
- 其他 provider
- 周/月视图
- dashboard 嵌入
- 模型粒度拆分

</user_constraints>

<architectural_responsibility_map>
## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 从本地 provider 数据源读取 usage | Rust/Tauri command | Filesystem | 本地路径与解析细节不应泄漏到 React |
| provider-specific 聚合规则 | Rust/Tauri command | Provider metadata | `Codex` 和 `Claude` 格式不同，需要后端边界收口 |
| 主导航 `Usage` tab | React app shell | i18n | 属于共享桌面壳层路由 |
| `Codex / Claude` 切换和表格展示 | React page | session presentation helpers | 纯显示层逻辑 |

</architectural_responsibility_map>

<research_summary>
## Summary

参考 `ryoppippi/ccusage` 后，最有价值的不是搬它的 CLI 或终端 UI，而是沿用它的两个核心统计原则：

1. `Codex` 不应只看总量快照，而应优先消费 `token_count` 事件里的 `last_token_usage`；如果只有累计值，则要用 `total_token_usage - previousTotals` 计算 delta。
2. `Claude` 不能简单逐行相加；同一逻辑回复可能重复落盘，需要基于 `message.id + requestId` 去重后再聚合 `message.usage`。

结合当前仓库结构，最稳的落点是新增一个 Tauri 命令 `get_provider_usage_summary`，让它按 provider runtime 读取本地文件并返回统一结构；React `UsageBrowser` 只关心 provider 切换和显示，不关心具体 jsonl 格式。

**Primary recommendation:** 延续现有 provider bridge 模式，在 `mac-app/src-tauri/src/commands/provider_usage.rs` 中实现 `Codex / Claude` 的 daily usage 读取和聚合，再通过 `invoke` 接入前端一级 `Usage` 页面。
</research_summary>

<standard_stack>
## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| React | 18.3.1 | `Usage` 页面状态与切换 | 当前桌面 UI 框架 |
| Tauri | 2.x | 前后端命令桥接 | 当前桌面宿主 |
| Rust + serde_json | current repo toolchain | 本地 jsonl 解析与聚合 | 已是 Tauri 命令层标准方案 |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| TypeScript | 5.6.2 | 定义 `ProviderUsageSummary` 前端 contract | 共享前端类型 |
| Node test runner | repo default | 静态 wiring 测试 | 验证主导航和页面接线 |

### External Reference
| Project | Purpose | Reused Insight |
|---------|---------|----------------|
| `ryoppippi/ccusage` | Claude/Codex usage aggregation reference | `Codex` delta 计算与 `Claude` 去重策略 |

</standard_stack>

<architecture_patterns>
## Architecture Patterns

### System Architecture Diagram

```text
User opens Usage tab
  -> App.tsx routes to UsageBrowser
    -> UsageBrowser requests get_provider_usage_summary(providerId)
      -> Tauri Rust command chooses provider runtime
        -> Codex reader scans ~/.codex/sessions/**/*.jsonl
        -> Claude reader scans ~/.claude/projects/**/*.jsonl
      -> Aggregated ProviderUsageSummary returns to UI
    -> UI renders provider switcher + fallback states + daily table
```

### Pattern 1: Shared contract, provider-specific reader
**What:** React 消费统一 summary 结构，Rust 内部按 provider 分支读取。  
**Why:** 这样共享 UI 不会知道 `Codex` 的 `token_count` 或 `Claude` 的 `message.usage` 细节。  
**Local fit:** 与已有 provider session / runtime bridge 模式一致。

### Pattern 2: Reference workflow borrowing, not wholesale copy
**What:** 借用 `ccusage` 的聚合和去重规则，不搬它的 CLI 入口和 terminal-oriented output。  
**Why:** 当前产品是桌面工作台，不是终端报表工具。

### Anti-Patterns to Avoid
- 在 `UsageBrowser.tsx` 里直接读取 `~/.codex` 或 `~/.claude`
- 把 `codex` / `claude` 的原始字段名直接扩散到共享前端组件
- 对 `Claude` 不做去重，导致 totals 被重复放大
- 把 `Codex` 的累计 totals 当作逐事件增量使用

</architecture_patterns>

<dont_hand_roll>
## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| provider 选择路由 | 新的全局状态系统 | 页面内本地 state | 只影响 `Usage` 页面 |
| provider-specific parsing in UI | 直接在 React 解析 jsonl | Rust command adapter | 保持 provider/plugin 边界 |
| fallback 页面骨架 | 新写一套状态展示组件 | 复用 `StatePanel` | 已有一致的工作台反馈模式 |

</dont_hand_roll>

<common_pitfalls>
## Common Pitfalls

### Pitfall 1: `Codex` 误把累计值重复累加
**What goes wrong:** 每次 `token_count` 都把 `total_token_usage` 直接累加，最终总量严重偏大。  
**How to avoid:** 优先用 `last_token_usage`；只有缺失时才用 `currentTotal - previousTotal`。

### Pitfall 2: `Claude` 不去重
**What goes wrong:** 同一个 assistant 回复在不同记录里重复出现，cost 和 token 被重复计入。  
**How to avoid:** 使用 `message.id + requestId` 做去重键。

### Pitfall 3: 把 provider enablement 和 usage support 混成一类错误
**What goes wrong:** UI 无法区分“provider 没启用”、“本地目录不存在”、“runtime 不支持 usage”。  
**How to avoid:** 统一返回 `unsupportedReason`，让 UI 做清晰 fallback。

</common_pitfalls>

<verification_strategy>
## Verification Strategy

- Rust 定向测试：
  - 验证 `Codex` delta 计算
  - 验证 `Claude` 去重逻辑
- Node 静态测试：
  - 验证 `Usage` tab 已进入主导航
  - 验证 `UsageBrowser` 已连接 provider switcher 和 usage loader
- 前端 build：
  - 验证 `App.tsx`、types、i18n、Usage page wiring 可编译

</verification_strategy>

---

*Phase: 02-provider-usage-explorer*
*Research completed: 2026-05-12*
