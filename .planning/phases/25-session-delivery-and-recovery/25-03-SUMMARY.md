---
phase: 25
plan: 03
status: source_verified
requirements: [DELIVERY-06]
---

# 25-03: 新建会话的分阶段恢复

## 最终行为

- `ThreadInfo.new_session_recovery` 随现有 AppStorage 原子写入，保存原始首消息、附件、request id、发送阶段和 IM 绑定阶段。真实 thread 创建后即保存，保持已有 source。
- 首消息前持久化 sending；接受后写入 sent。超时、取消等未知结果阻止重发；明确拒绝可重试。sent 的重试只补保存，不再次发送。进程退出后磁盘上的 sending 也按不确定结果处理。
- App 新建 composer 对同一内容保留 request id，Rust 将其传递到 owner bridge；并发相同请求共享一个创建任务。响应保留真实 thread、接受状态与恢复错误，界面明确显示失败。
- Telegram `/new` 创建或绑定 topic 失败时，仍保留真实会话并执行首消息。`/new --resume <session-id>` 复用恢复记录，只补未完成步骤；已发送首消息不重发，不确定结果继续拒绝重发。已创建但未绑定的 topic 可以复用。
- 删除旧 `/new` 失败回滚 helper，不再移除真实 thread、删除或关闭已创建 topic。
- 恢复状态和错误统一发布 `session.recovery.updated`；Task Board 与会话流消费总线投影。恢复成功清除恢复错误，同时保留期间到达的 provider 完成状态。

## 验证

- `python3 -m pytest -q tests/test_provider_session_new.py tests/test_slash_router.py tests/test_provider_owner_bridge.py -k 'new or starts_real_session or start_session or recovery_projection' --tb=short`：28 passed，71 deselected。
- `python3 -m pytest -q tests/test_message_event_bus.py --tb=short`：31 passed。
- `node --test mac-app/tests/sessionNewComposer.test.mjs mac-app/tests/sessionAsyncBoundaries.test.mjs`：6 passed。
- `cargo test --manifest-path mac-app/src-tauri/Cargo.toml start_provider_session_message_uses_owner_bridge_payload --quiet`：1 passed；测试需要临时 Unix socket，解除沙箱 socket 限制后通过。
- `pnpm --dir mac-app exec tsc --noEmit`：通过。
- `git diff --check`：通过。

## 验证边界

源码交付完成。25-03 改动尚未重新打包、覆盖安装或做安装版功能验证，不能宣称安装版 UAT 通过。本轮未提交，未向外部 IM 发送测试消息。

## 快速打包安装验证

用户授权后执行 `bash scripts/verify-packaged-fast.sh`：退出码 0，耗时 83 秒。四处版本一致为 `1.10.1`；Python sidecar、前端与 Rust/Tauri 构建完成，生成 `mac-app/src-tauri/target/release/bundle/dmg/OnlineWorker_1.10.1_aarch64.dmg`，覆盖 `/Applications/OnlineWorker.app` 并重启，脚本确认 App 与主 Bot 从安装目录运行。

快速打包安装验证通过；真实新建/恢复的安装版功能 UAT 尚未执行，未向外部 IM 发送测试消息，未提交。

## 安装反馈：Telegram 旧告警清除

修复 Dashboard 依赖已禁用 HTTPX 成功日志的问题：getUpdates transport 通过原生响应 hook 写入不含 token/URL 的专用成功或失败标记；Dashboard 优先使用这些标记，并在 PTB 新启动时重置历史结果。超过 90 秒的旧错误改为未知状态，普通消息网络错误不覆盖已有 polling 标记。

聚焦验证通过：Python 3 个检查、Rust 4 个检查。沿用用户授权的 `bash scripts/verify-packaged-fast.sh`，退出码 0，耗时 90 秒，已覆盖安装并重启。安装版连续记录 polling 成功标记，验证了新的恢复信号。

## 后续精简与验证（2026-09-30）

移除事件流迁移后失去调用方的会话轮询、Task Board 预览补读、旧事件 formatter 和审批完成包装；删除只写不读的 ref，复用 ThreadInfo 默认值，统一首消息成功出口及 Rust 流错误构造。生产代码净减 725 行，废弃接口测试净减 393 行；审批清理和跨 provider 隔离检查保留并改为验证现有 helper。

- `python3 -m pytest -q tests/test_provider_session_new.py tests/test_provider_owner_bridge.py tests/test_codex_runtime.py tests/test_session_stream_recovery.py tests/test_message_delivery_failures.py tests/test_slash_router.py --tb=short`：137 passed、1 skipped；8 个 Unix socket 检查因沙箱权限失败，解除限制后定向补验 8 passed，总计 145 passed、1 skipped。
- `node --test --test-reporter=dot mac-app/tests/taskBoard.test.mjs mac-app/tests/taskBoardConversationRefresh.test.mjs mac-app/tests/sessionPolling.test.mjs mac-app/tests/replyWatch.test.mjs mac-app/tests/sessionMerge.test.mjs mac-app/tests/providerSessionEventStream.test.mjs mac-app/tests/sessionMetadataBadges.test.mjs mac-app/tests/sessionAsyncBoundaries.test.mjs mac-app/tests/codexSessionSnapshotMerge.test.mjs mac-app/tests/appShell.test.mjs mac-app/tests/sessionNewComposer.test.mjs`：84 passed。
- `rtk cargo test --manifest-path mac-app/src-tauri/Cargo.toml commands::provider_sessions::tests --quiet`：22 passed；Unix socket 检查在解除沙箱限制后通过。
- `pnpm --dir mac-app exec tsc --noEmit`、Rust 文件格式检查及 `git diff --check`：通过。

用户授权后执行 `bash scripts/verify-packaged-fast.sh`：退出 0，耗时 94 秒；`1.10.1` sidecar 与应用重建，DMG 已覆盖安装并重启，App 和主 Bot 从安装目录运行。功能 UAT 仍未宣称通过。

随后版本字段、锁文件和打包文档统一更新为 `1.11.0`；`python3 -m pytest -q tests/test_version_sync.py --tb=short`：5 passed。该版本号更新尚未重新打包安装。
