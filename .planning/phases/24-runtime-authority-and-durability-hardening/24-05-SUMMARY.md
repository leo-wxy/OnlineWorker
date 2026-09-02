---
phase: 24
plan: 05
status: completed
completed_at: "2026-08-30T21:06:30+08:00"
---

# 24-05 Summary: service 与 stream 所有权

- Session event stream cleanup 已绑定实际 `stream_id`，覆盖启动完成晚于组件卸载以及旧 cleanup 晚到两类竞态。
- Bot service 的启动提交、monitor 清理和 crash restart 已绑定 generation/pid；stop 与 app exit 会使旧异步任务失效。
- service guard 现在显式读取 App 退出状态，退出窗口内不会重新触发 autostart。
- 最小回归通过：Node `6 passed`；相关 Rust 回归包含在全量 `253 passed` 中。
- 退出 guard 定向 Rust 回归：`1 passed`；`cargo fmt --all -- --check` 与 `git diff --check` 通过。
- 未执行 build、package、install、restart、commit 或 push。
