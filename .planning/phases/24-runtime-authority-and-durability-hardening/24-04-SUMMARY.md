---
phase: 24
plan: 04
status: completed
completed_at: "2026-08-30T19:36:52+08:00"
---

# 24-04 Summary: 增加 provider ingress 原子 source claim

## Completed

- `CodexAdapter` 以 `(session_id, turn_id, started|commentary|completed)` 建立最多 500 项的 private source claim，pending 按 `app-server > hook > notify > rollout` 仲裁，committed owner 不被迟到来源替换。
- app-server 与 external ingress 在第一次可见副作用前提交 claim；category、session authority、raw source visibility/trust、callback failure 和既有 completed dedupe 合同均保持明确。
- rollout 删除 adapter 外的 session-level app-server authority 预过滤，保留 watched/owned-thread 过滤，避免 external 已 committed 后双方互相抑制。

## Verification

- 红灯：`python3.13 -m pytest tests/test_codex_adapter.py -k source_claim -q` → `8 failed, 51 deselected`
- 绿灯：同一命令 → `8 passed, 51 deselected`
- `python3.13 -m pytest tests/test_codex_adapter.py -q` → `59 passed`
- `python3.13 -m pytest tests/test_codex_external_ingress.py tests/test_provider_owner_bridge.py tests/test_events_streaming.py -q` → `126 passed`
- `python3.13 -m py_compile plugins/providers/builtin/codex/python/adapter.py tests/test_codex_adapter.py` → passed
- `git diff --check` → passed

## Scope

- 未修改公开 IPC、SessionEvent、MessageEvent schema、依赖、TUI mirror、service lifecycle、持久化或构建配置。
- claim 只保存在进程内，按固定 500 项上限淘汰最旧 committed；跨重启恢复留给 24-06。
- 未执行 build、package、install、restart、commit 或 push。
