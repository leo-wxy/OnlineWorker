# Phase 24-04 Research: Provider Ingress 原子 Source Claim

## Question

怎样让 `app_server > hook > notify > rollout` 在并发到达时只保留一个用户可见来源，同时不修改公开 IPC、MessageEvent schema 或 TUI 结构？

## Verified Current State

- app-server 在 `CodexAdapter._dispatch()` 中进入顺序 event queue；hook/notify 经 owner bridge 的独立 task 直接调用 `ingest_external_hook_payload()`；rollout 最终也汇入该方法。
- `_authoritative_live_sessions` 只有 session 粒度；rollout `_fallback_tasks` 只有 `(session, turn, started|completed)` 的待执行 task；两者都不记录 source winner。
- EventBus 是事件到达后的 canonical dedupe，不能撤回已经执行的 provider/Telegram 副作用，也不表达 source priority。
- rollout started/completed 有 grace delay，notify 有 bridge delay，但 rollout commentary 无 delay；所有现有抑制均是观察式检查，检查和 emit 之间存在竞态。
- rollout 进入 adapter 前还通过 `_should_publish_session()` 做 session 级 app-server authority 预过滤；若 external 已 committed 而 app-server 后到，这道过滤会让双方都不再发布，因此必须把 live source 仲裁集中到 adapter。
- TUI realtime mirror、startup bootstrap 和 legacy final poll 绕过 `CodexAdapter`；它们不属于四个 provider ingress 的本切片合同。

## Minimal Design

在 `CodexAdapter` 内保留一个有界 private claim map：

```text
key    = (session_id, turn_id, started|commentary|completed)
value  = (source, committed, waiters, opaque_candidate_token)
order  = app_server > codex_hook > codex_notify > codex_rollout
```

- app-server 在 queue 前同步提交 claim。
- external source 先登记 pending candidate，主动让出一次 event-loop，再提交；并发的更高优先级 source 可在这段窗口替换 candidate。
- claim 一旦 committed，其他 source 不再替换，避免低优先级已经输出后高优先级再次产生不可回滚的副作用。
- 同一 source 可继续提交同类多条 commentary；started 与 completed 分开 claim，保留现有“hook start + notify completion”链路。
- session 已进入 app-server live authority 且当前 category 尚无 committed owner 时，由 app-server 占有该 category。
- claim 表最多 500 项。新 key 优先淘汰最旧 committed；全表都是 pending 时，仅拒绝 unseen external key，app-server 可淘汰最旧 pending。每个 waiter 持有 record identity/token，提交时必须仍匹配当前 map record；被淘汰的旧 waiter 不能提交，也不能把同 key 后续的新 record 误删或重新插入。取消任务只在 token 仍匹配且自己是最后 waiter 时移除 pending。
- app-server category 映射固定为：`turn/started → started`；`item/agentMessage/delta → commentary`；`item/completed + item.type=agentMessage + phase=commentary → commentary`；`item/completed + item.type=agentMessage + phase=final_answer → completed`；`turn/completed → completed`。shell、approval、其他 item 不 claim。
- app-server 事件缺失 `turn_id` 时不 claim，但现有 user-visible notification 仍可建立 session authority；external 缺失 provider `turn_id` 时保留现有单次 UUID fallback。由于不同入口无法可靠关联，该输入不宣称跨 source 去重。
- category gate 顺序固定为：先检查当前 key 的 committed owner；若没有 committed owner，再应用 `_authoritative_live_sessions`；迟到 app-server 不能替换已 committed external owner，claim 失败不得进入 `_event_queue`。无 claim 的可见 app-server shell/approval 仍建立 session authority，之后仅抑制尚无 committed owner 的 external category。
- source claim 成功并 committed 后，才允许调用 `_record_external_primary_event()`、取消 rollout fallback 或执行第一次 user-visible emit；pending 被替换、capacity reject、authority suppress 均不得产生这些副作用。
- rollout 仍保留 watched-thread 与 OnlineWorker-owned-thread 过滤，但不再在 `_should_publish_session()` 根据 app-server live session 提前返回；category winner 只由 adapter claim 决定。

## Security and Failure Boundaries

- external payload 的 raw source 继续只用于既有 visibility/trust 判断；另行派生 claim-only `ingress_source`。claim source 只接受 `codex_hook`、`codex_notify`、`codex_rollout`，未知值按 hook 优先级处理，外部 payload 不能伪造 `codex_app_server`。归一化不得覆写 raw payload，也不得让 subagent raw source 变为可见或让 spoof source 获得 hook transcript trust。
- claim 操作本身不 `await`，check/update 在同一个 event-loop turn 内完成；只有 external candidate 在提交前 `await asyncio.sleep(0)`。
- callback、Topic 或通知路由失败不释放 committed claim，避免部分副作用后 fallback 再次输出。
- `_authoritative_live_sessions` 保持现有合同：app-server live session 会占有尚无 committed owner 的 category；已有 external committed owner 不被迟到 app-server 回滚。
- 已完成 turn 的既有 `deduped=True` 返回语义先于新 claim denial 保留，避免把历史兼容合同统一改成 `suppressed`。

## Verification Targets

- notify/rollout 即使先开始 pending，concurrent hook 仍赢得相同 completion category。
- external pending 后 app-server 到达时，external 返回 suppressed 且只派发 app-server event。
- lower source 已 committed 后，迟到的其他 source不能生成第二条同类可见事件。
- hook started 与 notify completed 仍可组成同一 turn。
- 500 个 pending 时 unseen external key fail closed 且容量不突破；app-server 可淘汰最旧 pending，被淘汰 waiter 即使同 key 被重新登记也不能提交到新 record。
- callback 抛错后 committed owner 保留，迟到 source 仍被 suppress。
- `source=codex_app_server`、未知字符串、大小写和空值不能从 external payload 获得 app-server priority；subagent raw source 仍不可见。
- external committed started 后，无 category 的 app-server 可建立 session authority；该 started owner 保留，但随后尚无 owner 的 external completed 被抑制。
- rollout 的 session-level publish filter 不再截断已 committed category，所有 live source 冲突到 adapter 后再裁决。

## Deferred

- TUI realtime mirror/startup bootstrap/legacy final poll 统一仲裁。
- service disconnect/reconnect generation 与 handle ownership（24-05）。
- 持久化 claim、event sourcing、TTL 和恢复（24-06 或有真实证据后再加）。
