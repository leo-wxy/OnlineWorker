# Phase 26: Codex Compressed Session History Support

Recorded: 2026-10-07
Status: Complete; source and installed compressed-history snapshot verified

## User Intent

支持 Codex 压缩会话历史，并在 Phase 26 中处理。采用 Ponytail 的最小实现方式，复用现有 provider、解析器与消息总线。

## Confirmed Cause

- 会话索引仍能提供元数据，但部分历史只保存为 `.jsonl.zst`。
- `storage_runtime.find_session_file()` 只匹配 `.jsonl`；找不到文件时，`read_thread_history()` 返回空列表。
- 已安装应用的会话 stream 返回空 `replace_snapshot`。将压缩输入流解码后交给相同解析器，可以读取最近 50 条消息，证明历史存在，缺口在文件格式支持。

## Scope and Decisions

- 用户明确限定：生产代码适配只写在 `plugins/providers/builtin/codex/python/`，禁止修改 `core/`。共享层只消费现有 provider facts 接口的结果。
- 统一支持 `.jsonl` 与 `.jsonl.zst` 的文件发现和只读文本流，复用当前消息归一化、去重及时间戳处理。
- 核对文件发现函数的所有调用者，覆盖 Codex 的历史、元数据和终态读取；实时增量消费者按原始 JSONL 的语义处理。
- 使用现有 `provider facts -> owner bridge -> session.history.loaded -> MessageEventBus` 链路，App 继续消费总线快照。
- 流式解压，历史文件保持原样；读取错误通过现有查询错误通道报告。
- 压缩历史按会话 ID 查找和读取；批量会话列表沿用 SQLite 元数据和普通 JSONL 索引，避免为显示列表解压全部历史。解压扩展不改变现有实时入口的调用行为。
- 解压能力随 Python sidecar 打包，并验证普通与压缩输入等价、错误输入及压缩会话快照。

## Implementation Anchors

- `plugins/providers/builtin/codex/python/storage_runtime.py`: 文件收集、文件名解析、历史/元数据/终态读取。
- 现有 provider facts 和消息总线接口：沿用当前历史加载事件和初始会话快照，作为集成验收边界。
- `tests/test_storage.py`, `tests/test_storage_extended.py`: 现有 provider 存储回归。
- `requirements.txt`, `onlineworker.spec`, `onlineworker-x86_64.spec`: 评估现有解压能力和 sidecar 打包边界。

Phase 25 的剩余验收按原记录跟踪。构建、覆盖安装、重启和推送按仓库授权规则执行。
