# Requirements: OnlineWorker

## Current Milestone

**Theme:** Notification Extensibility

The v1.2.1 milestone requirements are archived at [milestones/v1.2.1-REQUIREMENTS.md](milestones/v1.2.1-REQUIREMENTS.md).

## Notification Channels

- [x] **NOTIFY-01**: User-facing notifications can be emitted through a plugin-based notification router rather than being limited to Telegram-specific notification channels.
- [x] **NOTIFY-02**: Telegram remains the default builtin notification plugin, and custom notification plugins such as WeChat can be inserted later without changing core notification routing.

## Attention Center And Session Controls

- [x] **ATTN-01**: User can use the existing Task Board Tab as a focused attention center grouped into `需要你`, `正在运行`, and `最近结束`, with a selected Session detail pane and authority-safe actions.
- [x] **SESS-CTRL-01**: User can interrupt a concrete provider-owned active turn and continue or recover the same real Session without fabricating local Session truth, replaying a prior message, or exposing controls for mirrored-only Sessions.

## Diagnostics And Support

- [x] **DIAG-01**: User can run bounded local diagnostics from Settings and receive independent pass, warning, or failure results for app version, managed service, provider readiness, owner bridge, configuration, plugins, sockets, and recent runtime errors even when some checks fail or the bot is stopped.
- [x] **SUPPORT-01**: User can export a local support ZIP containing a human-readable summary, structured diagnostic facts, sanitized configuration shape, provider/plugin inventory, and a bounded recent log excerpt, then reveal the generated file in Finder.
- [x] **PRIV-01**: Diagnostics and support bundles exclude raw credentials, tokens, environment values, complete Session conversations, prompts, provider transcript/history files, and automatic network upload.

## Runtime Stability

- [x] **STAB-01**: MessageEventBus dedupe retention is bounded while recent duplicates remain suppressed.
- [x] **STAB-02**: Runtime read failures remain errors and do not replace last-known-good state with fabricated empty data.
- [x] **STAB-03**: Stale turns, generations, stream cleanup, and delayed requests cannot overwrite a newer owner.
- [x] **STAB-04**: One provider ingress/live chain owns each user-visible session turn event category.
- [x] **STAB-05**: Critical config/state writes are atomic and recoverable, and route migrations can safely resume.
- [x] **STAB-06**: Each stability slice has focused automated regression coverage.

## Session Delivery and Recovery

- [x] **DELIVERY-01**: 发送与归档只在请求写入前自动重试，结果不确定时不重复执行。
- [x] **DELIVERY-02**: 会话状态由 Python AppStorage 统一写入；配置并发与陈旧全文保存不会丢更新。
- [x] **DELIVERY-03**: 旧 stream、归档、发送和附件结果不能更新新的 provider/session/workspace 选择。
- [x] **DELIVERY-04**: 慢 IM 消费不阻塞 MessageEventBus 发布、本地状态与会话投影。
- [x] **DELIVERY-05**: 流发送积压有界，断线后通过消息中心快照恢复，无静默丢失或重复。
- [x] **DELIVERY-06**: 新建与首消息失败保留真实会话和恢复状态，重试不创建或发送第二份。
- [ ] **DELIVERY-07**: 普通发送与新建请求在失败、结果未知和重启后可追踪并由用户安全核实、恢复；未知结果不自动重发。
- [ ] **DELIVERY-08**: App 可展示并回答 provider 的真实 question 请求，过期、已处理和仅镜像请求不会重复回写。
- [ ] **DELIVERY-09**: 通知未送达状态可按渠道查看并在重启后恢复，用户可显式补发通知且不会重新执行任务或审批。
- [ ] **DELIVERY-10**: 主 Sessions 支持标题、目录和近期摘要关键词搜索，并与 provider、工作区和归档筛选协同。
- [ ] **DELIVERY-11**: 账号 Apply 与当前连接、会话的实际生效范围可区分已确认和未知，不伪造切换成功。
- [ ] **DELIVERY-12**: App 提供检查版本与官方发布入口；架构产物、签名和公证在条件具备后有可验证的发布流程。

新增范围与验收标准见 [Phase 25 补充](phases/25-session-delivery-and-recovery/25-FOLLOWUP.md)。STAB-07 作为条件项在该阶段跟踪，仍保留延期状态；25-02/25-03 的既有功能 UAT 不因补充需求而视为完成。

## Codex Compressed Session History

- [x] **HIST-01**: Codex `.jsonl.zst` 历史可通过现有会话详情读取，保留与 `.jsonl` 一致的消息内容、phase、时间戳和去重行为（源码及安装版初始快照验证通过）。
- [x] **HIST-02**: 压缩格式适配仅在 Codex 插件内部实现，禁止修改 `core/`；历史、元数据及终态读取共享该能力，通过已有 provider facts 与 MessageEventBus 接口向现有消费者提供结果（源码验证通过）。
- [x] **HIST-03**: 压缩历史读取失败明确可诊断；打包应用自带解压能力，不依赖用户机器额外安装的 CLI（源码异常回归及安装版解压验证通过）。

## Deferred Backlog

- [ ] **STAB-07**: OnlineWorker can discover the current Codex session owner, steer/queue ordinary TG input through that owner, invoke its real interrupt capability, and return commentary/final to the original TG Topic. Deferred from Phase 24 by user acceptance; not implemented/verified. Resume only when supported owner control becomes available; preserve the acceptance criteria in [24-07-PLAN.md](phases/24-runtime-authority-and-durability-hardening/24-07-PLAN.md).

These items remain candidates for future work. UX/PLT items came from v1.2.1; STAB-07 was deferred by explicit user acceptance when Phase 24 was archived on 2026-09-05.

- **UX-01**: User can customize more of the app appearance from first-class settings surfaces.
- **UX-02**: User can discover and configure external provider extensions from a richer in-app management experience.
- **PLT-01**: User can use equivalent first-class desktop packaging flows beyond macOS.
- **PLT-02**: User can use richer release automation including signing/notarization without manual release intervention.

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| NOTIFY-01 | Phase 6 | Implemented |
| NOTIFY-02 | Phase 6 | Implemented |
| ATTN-01 | Phase 19 | Complete; installed desktop UAT passed, narrow visual check explicitly waived |
| SESS-CTRL-01 | Phase 19 | Implemented; installed interrupt, Continue, recovery, no-replay UAT passed |
| DIAG-01 | Phase 20 | Complete; source and installed diagnostics UAT passed |
| SUPPORT-01 | Phase 20 | Complete; installed export, cancellation, and Finder reveal passed |
| PRIV-01 | Phase 20 | Complete; strict ZIP whitelist and installed `.env` zero-match privacy scan passed |
| STAB-01 | Phase 24 | Source verified in 24-01 |
| STAB-02 | Phase 24 | Source verified in 24-02 and 24-08 |
| STAB-03 | Phase 24 | Source verified in 24-03, 24-05, and 24-08 |
| STAB-04 | Phase 24 | Source verified in 24-04 and 24-06 |
| STAB-05 | Phase 24 | Source verified in 24-06 and 24-08 |
| STAB-06 | Phase 24 | Source verified through 24-09; fast packaged verification passed; feature UAT not run and accepted as an archival limitation |
| STAB-07 | Deferred backlog (from Phase 24) | Deferred by user acceptance on 2026-09-05; original owner-control gap and acceptance criteria preserved in 24-07 |
| DELIVERY-01 | Phase 25 / 25-01 | Complete |
| DELIVERY-02 | Phase 25 / 25-01 | Complete |
| DELIVERY-03 | Phase 25 / 25-01 | Complete |
| DELIVERY-04 | Phase 25 / 25-02 | Source and fast package verified; feature UAT pending |
| DELIVERY-05 | Phase 25 / 25-02 | Source and fast package verified; feature UAT pending |
| DELIVERY-06 | Phase 25 / 25-03 | Source and fast package verified; feature UAT pending |
| DELIVERY-07 | Phase 25 / Follow-up | Scope recorded; implementation and UAT pending |
| DELIVERY-08 | Phase 25 / Follow-up | Desktop reply and question lifecycle fixes source verified; feature UAT pending |
| DELIVERY-09 | Phase 25 / Follow-up | Scope recorded; implementation and UAT pending |
| DELIVERY-10 | Phase 25 / Follow-up | Scope recorded; implementation and UAT pending |
| DELIVERY-11 | Phase 25 / Follow-up | Scope recorded; implementation and UAT pending |
| DELIVERY-12 | Phase 25 / Follow-up | Updater, release flow and review fixes source verified; release prerequisites and feature UAT pending |
| HIST-01 | Phase 26 / 26-01 | Source and installed initial-snapshot verified |
| HIST-02 | Phase 26 / 26-01 | Source verified; production changes confined to Codex plugin history reading and startup metadata |
| HIST-03 | Phase 26 / 26-01 | Read errors source verified; installed package decoder verified |
