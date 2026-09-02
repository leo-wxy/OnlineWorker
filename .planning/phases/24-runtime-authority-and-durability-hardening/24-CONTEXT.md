# Phase 24: Runtime Authority and Durability Hardening — Context

## Goal

让 provider 事件、session/activity 状态、service/stream 生命周期和持久化记录各自只有一个明确权威入口，避免长期运行、事件乱序、短暂 IPC 故障或进程中断造成重复消息、状态回退、假空快照和不可恢复数据。

## Locked Decisions

1. 按影响由小到大实施，每个切片独立验证后再进入下一项。
2. 复用现有 `MessageEventBus`、`SessionActivityProjection`、provider adapter、Tauri command 和存储模块，不引入新框架或依赖。
3. provider 可见消息来源优先级固定为 `app_server > hook > notify > rollout`；fallback 不能与权威 live chain 并行输出同一可见事件。
4. Topic 和通知路由只属于 terminal outbound；路由失败不能阻塞 provider、EventBus、projection 或 Task Board。
5. 读取失败必须与成功空结果区分；失败保留 last-known-good，并显式暴露 stale/error。
6. 不以文件大小为理由重写模块，只在当前变更触达的 shared seam 修复一次。

## Ordered Slices

1. 有界 EventBus 去重记账。
2. snapshot/IPC 失败语义与 last-known-good。
3. canonical publish、turn 顺序和 snapshot/delta generation。
4. provider ingress 原子 source claim。
5. service/stream generation 或 handle 所有权。
6. 原子持久化、恢复、幂等迁移与集成回归。

## Non-Goals

- 不实现完整 event sourcing 或持久化事件审计日志。
- 不新增状态管理、消息队列、缓存或数据库依赖。
- 不重写 Python/Rust/React 技术栈与 provider/notification 插件 seam。
- 不在本 Phase 处理 Settings 并发保存合同或 combined release ownership；它们保留为后续独立工作。
- 未经当前对话明确授权，不 build、package、install、restart 或 push。
