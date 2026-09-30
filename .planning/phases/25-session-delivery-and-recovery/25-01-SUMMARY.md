---
phase: 25
plan: 01
status: complete
requirements: [DELIVERY-01, DELIVERY-02, DELIVERY-03]
---

# 25-01 实施与验证

发送只在 owner bridge 连接建立前等待重试；连接后请求只写一次，响应丢失、解析失败和业务拒绝均返回错误。归档主状态写入移到 Python AppStorage；App、Telegram 和启动同步复用提交与总线发布入口，Rust 仅保留状态读取，本地覆盖归档使用明确模式。

前端 Channel 在 cleanup 后忽略事件，聊天 key 包含完整 provider/session/workspace；发送、附件与归档完成回调按当前身份失效。配置与环境设置的读改写共用写锁，全文编辑携带读取时 revision，陈旧保存被拒绝。

发送事件共用 messageRequestId，后台排队使用 message.user.queued，provider 发送成功才发布 accepted，失败发布 message.user.send_failed；超时和连接错误标记 uncertain。旧请求失败不能覆盖较新输入，发送失败不伪造 turn.failed，也不终止已经运行的 provider turn。

## 源码检查

- `python3 -m pytest -q tests/test_message_delivery_failures.py tests/test_message_event_bus.py tests/test_provider_session_new.py`：43 passed。
- `python3 -m pytest -q tests/test_provider_owner_bridge.py tests/test_codex_owner_bridge.py tests/test_slash_router.py tests/test_handlers.py`：118 passed；Unix socket 测试使用临时目录所需权限。
- `python3 -m pytest -q tests/test_thread_controls.py tests/test_session_archive_authority.py tests/test_storage.py`：此前关联运行中全部通过。
- `python3 -m pytest -q tests/test_startup_runtime.py -k '(archive or subagent) and not ensure_thread_topics'`：5 passed。
- `cargo test --lib commands::provider_sessions::tests -- --nocapture`：22 passed。
- `cargo test --lib commands::config::tests -- --nocapture`：16 passed，包含并发设置和旧 revision 拒绝。
- `node --test --test-reporter=dot mac-app/tests/*.test.mjs`：退出 0；会话身份、迟到发送、归档与附件边界的 8 个目标检查通过。
- `./mac-app/node_modules/.bin/tsc -p mac-app/tsconfig.json --noEmit` 与 `git diff --check`：退出 0。

## 安装版检查

经用户明确授权执行 `bash scripts/verify-packaged-fast.sh`，退出 0，耗时 95 秒；sidecar 已重建，版本四处均为 1.10.1，DMG 已覆盖到 `/Applications/OnlineWorker.app`，新 App 与 Bot 从安装路径运行。

只读 IPC 确认 Codex health 为 healthy，当前运行中会话恢复。通过安装版任务页确认重启后的新回复自动更新到卡片与会话片段，全程未点击刷新。该结果覆盖本批功能回归，不代表完整历史 UAT 或 Telegram 网络恢复。

现有启动测试中两项依赖 Codex 自动创建 TG topic 的断言在原实现也失败；本批未更改该 provider 策略。离线归档要求服务恢复后重试；结果不确定不自动重发，未引入跨进程持久幂等 journal。
