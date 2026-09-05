---
phase: 24
plan: 01
status: completed
completed_at: "2026-08-30T17:54:07+08:00"
---

# 24-01 Summary: 限定 MessageEventBus 去重保留窗口

## Completed

- `MessageEventBus.publish()` 在 recent-events deque 即将淘汰最老事件时，同步移除该事件的非空 dedupe key。
- 保留窗口内重复 publish 返回 `False` 的既有行为。
- 增加回归测试，证明 key 离开事件环后可被回收并重新接收，同时事件环长度仍受 `max_events` 限制。

## Verification

- `python3.13 -m pytest tests/test_message_event_bus.py -q` → `26 passed in 0.35s`
- `git diff --check` → passed

默认 `python3` 指向 Python 3.14 且没有安装 pytest，因此首次命令未进入测试；未安装依赖，改用项目已有 Python 3.13.1 完成验证。

## Scope

- 未修改公开接口、provider ingress、projection、UI、IPC、配置、依赖或构建脚本。
- 未执行 build、package、install、restart 或 push。
