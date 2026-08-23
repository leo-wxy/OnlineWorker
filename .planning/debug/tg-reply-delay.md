---
status: resolved
trigger: "消息传回 TG 很慢，TG 仍显示上一条消息"
created: 2026-08-23
updated: 2026-08-23
---

# Telegram reply delay

## Symptoms

- expected: Codex 产生 commentary/final 后，Telegram 在数秒内显示对应的新一轮内容。
- actual: 入站 queue 成功，但 Telegram 长时间仍显示上一轮消息。
- error: 无显式发送错误。
- timeline: active-writer queue 降级启用后的实机验证中出现。
- reproduction: 从 Telegram 向 Codex Desktop 正在持有的 thread 发送消息。

## Current Focus

- hypothesis: App 模式的 session mirror 在工具调用期间把 commentary 空闲误判为 turn 完成，抢先标记 final 已同步，导致稍后真实 final 被去重丢弃；打包环境缺少 watchfiles 又放大了事件捕获延迟。
- test: App 模式 commentary 后连续空闲轮询不得发出 turn/completed；TUI 模式保留原空闲兜底。
- expecting: 真实 final 到达前不完成当前 turn；恢复 FSEvents 后 commentary/final 能及时捕获。
- next_action: run Telegram acceptance test

## Evidence

- 21:34:15.856 Telegram 入站，21:34:16.446 `codex queue` 投递成功，入站耗时约 0.6 秒。
- 当前 turn 的第一条 commentary 于 21:34:27.714 写入 rollout，OnlineWorker 到 21:34:35.979 才建立 streaming 消息。
- OnlineWorker 于 21:34:47.299 将 turn 标为完成，但 rollout 的真实 `final_answer` 到 21:35:18.075 才产生。
- 真实完成事件于 21:35:22.862 被当作“已同步 duplicate”跳过，因此 Telegram 保留了错误的早期内容。
- 打包日志明确记录 `missing module named watchfiles`，运行日志记录 Desktop rollout ingress 启动失败。

## Eliminated

- Telegram 入站或 `codex queue` 慢：queue 在约 0.6 秒内成功。
- Telegram API 发送失败：日志显示 edit/send 调用成功，无网络错误。

## Resolution

- root_cause: App/共享模式把 commentary 连续空闲轮询误判为 turn 完成；真实 final 随后被“已同步”状态去重。构建环境缺少已声明的 watchfiles，使事件捕获退回慢轮询。
- fix: 仅 TUI 模式保留 commentary idle completion；App/共享模式等待真实 final。补装 watchfiles 1.1.1，恢复 FSEvents rollout ingress。
- verification: realtime mirror、external ingress、streaming events、Codex runtime 组合回归 98 项通过；watchfiles 版本和真实 FSEvents 测试均已确认；1.9.0 DMG 已覆盖安装，启动日志确认 Desktop rollout ingress 正通过 FSEvents 监听。
- files_changed: plugins/providers/builtin/codex/python/tui_realtime_mirror.py, tests/test_codex_tui_realtime_mirror.py
