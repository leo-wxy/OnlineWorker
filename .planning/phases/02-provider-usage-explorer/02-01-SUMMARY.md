---
phase: 02-provider-usage-explorer
plan: 01
subsystem: provider-usage
tags: [tauri, rust, provider-boundary, codex, claude, usage]
requires: []
provides:
  - 统一的 provider usage summary contract
  - Codex 本地按日 token 聚合
  - Claude 本地按日 token 聚合与去重
affects: [desktop-usage-page, provider-runtime-bridge]
tech-stack:
  added: []
  patterns: [provider-specific-reader, shared-summary-contract, local-jsonl-aggregation]
key-files:
  created: [mac-app/src-tauri/src/commands/provider_usage.rs]
  modified:
    - mac-app/src-tauri/src/commands/mod.rs
    - mac-app/src-tauri/src/lib.rs
    - mac-app/src/components/session-browser/api.ts
    - mac-app/src/types.ts
requirements-completed: [USG-01, USG-02]
completed: 2026-05-12
---

# Phase 2 Plan 01 Summary

## Accomplishments

- 新增 `get_provider_usage_summary` Tauri 命令，并挂到 shared invoke handler
- 定义 `ProviderUsageDay` / `ProviderUsageSummary` 共享 contract
- 为 `Codex` 实现本地 `token_count` daily aggregation
- 为 `Claude` 实现本地 `message.usage` daily aggregation，并对 `message.id + requestId` 去重
- 为 `Codex` 增加重复 `token_count` 快照去重，避免 `last_token_usage / total_token_usage` 成对出现时统计翻倍
- 为 `Codex` 增加日期目录裁剪，只扫描命中时间窗口的 `YYYY/MM/DD` 目录，避免 `Usage` 页面默认加载时全量递归历史会话

## Key Decisions

- 解析逻辑保持在 Rust provider 命令层，避免把 provider-specific jsonl 结构扩散到 React
- `Codex` 优先用 `last_token_usage`，累计值只用于 delta fallback
- `Claude` 的 usage 聚合必须先去重，再累计 cost 与 token
- `Codex` 的重复快照不能直接累加；同一轮 totals 未变化时视为同一个 usage snapshot
- `Usage` 查询默认带时间范围，provider 读取层必须先按日期裁剪，再做逐文件聚合

## Verification

- `cargo test --manifest-path mac-app/src-tauri/Cargo.toml provider_usage --quiet`

## Known Limits

- 当前只覆盖 builtin `codex` / `claude`
- 仅做按日聚合，不提供周/月视图
- 时间范围仍以按日窗口为主，不提供更细粒度模型维度拆分

---
*Completed: 2026-05-12*
