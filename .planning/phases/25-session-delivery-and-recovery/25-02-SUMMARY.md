---
phase: 25
plan: 02
status: source_verified
requirements: [DELIVERY-04, DELIVERY-05]
---

# 25-02: 消费隔离、流积压上限与重连恢复

## 结果

- Provider 普通事件和 app-server 审批先经 MessageEventBus 更新本地状态，再由每个 provider 共用的有序 IM 消费者执行网络操作；相邻 delta 合并，队列上限 256，满队列明确发布出站失败。
- Task Board 活动流与会话流每条连接只有一个发送 worker 和最多 256 条待发送数据；溢出关闭连接，重连从消息中心快照恢复。
- 消息中心保留最近 50 条会话正文及 turn/item 身份；Task Board 继续使用 6 条摘要。完整正文不进入公开事件记录。
- 会话页移除定时补读和发送后轮询，首屏、手动刷新和重连均由总线派生快照提供。
- Provider 断开、重新 setup 和关闭会取消旧消费者、订阅与节流任务。Codex 审批清除的 Telegram edit 也进入同一消费者。
- 总线拒绝已知会话的冲突绝对 workspace 路径事件，防止恢复快照混入另一 workspace 的内容。

## 本次收尾验证

- `python3 -m pytest -q tests/test_session_stream_recovery.py tests/test_message_event_bus.py tests/test_provider_owner_bridge.py --tb=short`：100 passed，2 条旧历史快照断言缺少现有 markdown displayMode。
- 更新上述 2 条断言后，分别重跑 `test_provider_owner_bridge_reads_latest_session_turns_via_provider_facts` 和 `test_provider_owner_bridge_does_not_treat_workspace_dir_as_sessions_dir`：2 passed。相关 102 个用例均已通过。
- 流测试停顿由断言失败后客户端未关闭引起；补充 finally 关闭和 1 秒等待上限后，真实失败可立即报告。
- 前一执行段已通过前端 202 passed / 1 skipped、TypeScript 检查、启动回归 71 passed；本段未改前端。
- `git diff --check`：通过。

## 验证边界

源码交付已完成。安装版功能验证尚未执行，不能宣称已安装验收。本段没有打包、覆盖安装、重启、提交或向外部 IM 发送测试消息。25-03 尚未实施。

## 快速打包安装验证

用户授权后执行 `bash scripts/verify-packaged-fast.sh`，退出码 0，耗时 95 秒。已重建 Python sidecar、通过 TypeScript/Vite 与 Rust/Tauri 构建，生成 `mac-app/src-tauri/target/release/bundle/dmg/OnlineWorker_1.10.1_aarch64.dmg`，覆盖 `/Applications/OnlineWorker.app` 并重启；脚本确认 App 与主 Bot 从安装目录运行。

快速打包安装验证通过。安装版自动刷新与重新打开会话后的内容恢复仍待界面验收，未宣称功能 UAT 通过。未向外部 IM 发送测试消息，未启动 25-03。
