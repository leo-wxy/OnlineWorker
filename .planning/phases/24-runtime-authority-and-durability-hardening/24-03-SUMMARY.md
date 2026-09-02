---
phase: 24
plan: 03
status: completed
completed_at: "2026-08-30T18:34:39+08:00"
---

# 24-03 Summary: 收敛 canonical publish、turn 顺序和前端 snapshot/delta 仲裁

## Completed

- canonical publish 现在区分 accepted、duplicate 与 unavailable；只有确认重复的事件跳过 provider handler，bus 不可用或异常仍保留原处理链。
- session activity projection 在共享入口拒绝非当前 turn 的迟到进度和终态；canonical dedupe 只使用稳定身份。
- Task Board activity 收敛为单一 stream 写源；Menubar 与 Session Chat 分别用现有时间戳/事件序列和本地 generation 丢弃旧 snapshot。

## Verification

- `/Users/wxy/.pyenv/versions/3.13.1/bin/python3 -m pytest tests/test_message_event_bus.py tests/test_events_streaming.py tests/test_codex_adapter.py -q` → `133 passed`
- `/Users/wxy/.pyenv/versions/3.13.1/bin/python3 -m pytest tests/test_provider_owner_bridge.py -q` → `63 passed`
- `node --test tests/appShell.test.mjs tests/menubarPopover.test.mjs tests/sessionPolling.test.mjs tests/providerSessionEventStream.test.mjs` → `42 passed`
- `git diff --check` → passed

## Scope

- 未修改 provider source priority、公开 IPC schema、stream/service lifecycle、持久化、依赖或构建脚本。
- 两个没有 source sequence 的 opaque `turn.started` 仍无法可靠比较先后；本切片不猜测 turn id 顺序。
- 未执行 TypeScript/Rust 编译、build、package、install、restart、commit 或 push。
