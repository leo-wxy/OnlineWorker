---
status: resolved
trigger: "发送消息先报 thread not found，恢复后报 already has an active writer"
created: 2026-08-23
updated: 2026-08-23
---

# Thread not found on send

## Symptoms

- expected: 在已有会话中发送消息后，provider 接收并处理该消息。
- actual: 发送失败。
- error: `thread not found`，随后是 `already has an active writer`
- timeline: 安装最新 1.9.0 构建后仍可复现。
- reproduction: 打开已有会话并发送消息。

## Current Focus

- hypothesis: 当前会话由 Codex Desktop app-server 持有单写锁，OnlineWorker 的独立 app-server 无法 resume；应通过 Codex 官方 queue 命令向活跃 writer 投递消息。
- test: 模拟 `turn/start` 返回 `thread not found`，随后 `thread/resume` 返回 `already has an active writer`。
- expecting: OnlineWorker 执行 `codex queue --thread ... --message ...`，不再争抢 writer。
- next_action: package and user acceptance send

## Evidence

- 2026-08-23 21:05:16：日志记录 `turn/start` 后立即返回 `thread not found`。
- 2026-08-23 21:05:22：app-server 第 9 次重连成功。
- 2026-08-23 21:05:24：连接初始化因 `No module named 'watchfiles'` 再次进入重连。
- 2026-08-23 21:21:37：首次恢复重试命中 `already has an active writer`，证明目标会话正由另一 app-server 持有。
- 现场进程显示 Codex Desktop 与 OnlineWorker 分别运行独立 app-server，不能共享同一会话的 writer。
- 本机 Codex CLI 提供 `codex queue --thread <THREAD> --message <TEXT>`，用于向现有活跃 session 排队消息。
- 当前打包 Python 环境无法导入 `watchfiles`，但依赖已列入 `requirements.txt`。
- `pytest -q tests/test_codex_runtime.py`：23 passed。
- `pytest -q tests/test_handlers.py tests/test_provider_owner_bridge.py tests/test_codex_runtime.py`：111 passed。

## Eliminated

## Resolution

- root_cause: 可选 Desktop rollout ingress 的导入失败会触发重连；更关键的是 Codex Desktop 已持有当前会话的单写锁，OnlineWorker 独立 app-server 的 resume/retry 必然触发 active writer 冲突。
- fix: watcher 启动失败降级为告警；普通未物化会话仍 resume/retry；明确命中 active writer 时改走官方 `codex queue`，同时保留文本和图片附件。
- verification: Codex runtime 定向测试 23 项通过，handler/owner bridge/runtime 回归共 111 项通过，`codex queue --help` 已确认命令和参数可用。新的 queue 修复尚未重新打包安装。
- files_changed: plugins/providers/builtin/codex/python/runtime.py, tests/test_codex_runtime.py
