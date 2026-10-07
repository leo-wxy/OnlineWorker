---
phase: 25
status: packaged_verified_partial_uat
created: "2026-10-01"
updated: "2026-10-07"
requirements: [DELIVERY-07, DELIVERY-08, DELIVERY-09, DELIVERY-10, DELIVERY-11, DELIVERY-12]
conditional_requirements: [STAB-07]
---

# Phase 25 补充：用户操作闭环与发布易用性

用户要求将整体功能评估中的缺口纳入 Phase 25。25-01 至 25-03 的既有实现和验证记录保留。2026-10-02 复审修复已完成源码回归、1.11.0 快速打包安装与部分桌面自测；新建选中项回退已修复并通过安装版 Codex 真实回归，完整功能 UAT 尚未通过。

## 2026-10-02 复审修复

- [x] 问题失效后清理 Telegram 自定义输入等待，避免后续普通消息被旧请求持续拦截。
- [x] 更新准入不再使用发送耗时指标判断忙碌；明确失败与准备阶段拒绝可收口，发送结果不确定仍阻止安装。
- [x] Codex proxy 不再伪造 turn 开始/完成；连接期间保护更新，断开时释放，`turn/steer` 失败不清除原 turn。
- [x] 总线中已隐藏、归档或不存在的问题不能继续回写 provider；真实 Claude 请求不存在或已完成时返回不可重试结果。
- [x] 普通本地构建不依赖发布 updater 私钥；正式发布仍必须生成有效签名。
- [x] 忙碌或无法确认空闲时不创建 App 备份；备份后重查并续期准入，失败释放准入。新建会话也纳入准入边界。
- [x] 同步 README、构建文档和阶段状态，补充签名密钥与公钥配对说明及实际验证边界。

实现限制：为避免另建逐 RPC 状态机，连接中的远程 CLI（包括空闲连接）必须先关闭才能安装；真实任务状态仍由总线提供。独立 CLI 与直连 provider 的外部客户端不由该锁控制。备份仍保留供人工恢复，不新增自动清理或重启健康回滚。

源码验证（2026-10-02；测试均使用合成数据和临时路径）：

- `python3 -m pytest -q tests/test_desktop_questions.py tests/test_question_enhanced.py tests/test_app_update.py tests/test_release_architectures.py tests/test_claude_adapter.py -k 'question or update or proxy_send_failure or remote_cli_connection or shared_build or release_workflow' --tb=short`：79 passed，44 deselected。
- `python3 -m pytest -q tests/test_app_update.py tests/test_message_delivery_failures.py tests/test_codex_remote_proxy.py tests/test_provider_owner_bridge.py --tb=short`：87 passed；11 项因沙箱禁止 Unix socket 被阻止，随后用所需权限执行 `python3 -m pytest -q tests/test_codex_remote_proxy.py tests/test_provider_owner_bridge.py --lf --tb=short`，11 passed。
- 最后补充准入用例后，`python3 -m pytest -q tests/test_app_update.py tests/test_message_delivery_failures.py --tb=short`：17 passed。
- `CARGO_HOME="$PWD/.onlineworker-local/cargo" cargo test --manifest-path mac-app/src-tauri/Cargo.toml --lib commands::app_update::tests --offline --quiet`：3 passed。
- `git diff --check`、`bash -n scripts/build.sh`、`python3 scripts/sync-app-version.py --check`：通过，版本 1.11.0。

本轮只修复以上已确认问题。DELIVERY-07 部分实现见下方普通发送恢复记录，DELIVERY-09、10、11 继续待实施；真实 updater 下载、签名拒绝、任务忙碌拒绝、安装失败恢复及重启恢复仍需单独的安装版功能验收，快速覆盖安装不替代这些验收。

## 2026-10-02 独立审查追加项与修复

按用户要求另行审查 25-01/02/03 的既有实现，随后获准继续修复以下 4 项。它们与上方 6 项分批验证，当前均已源码验证并重新打包安装；安装版验证结果见下一节。

- [x] **P1：新建 pending 认领缺少请求身份。** 恢复事件、Python/Rust 活动投影和桌面状态已传播 `newSessionRequestId`；只匹配创建 request、provider 与 workspace，删除时间/文本相似度认领。更新 pending 状态时也检查当前 composer 身份。
- [x] **P1：桌面发送的目标校验不足。** 目标按 provider 查找，校验目录、归档与对象绑定；外部会话首次接入必须由 provider 事实确认仍属于目标工作区，未知目标不生成本地记录。后台发送及新建首消息真正提交前再校验；失效绑定不会被回滚逻辑覆盖。已覆盖相同 session ID 跨 provider、排队后归档/替换/移除工作区。
- [x] **P2：桌面入口提前绕过 provider 重连等待。** 普通发送和新建先使用既有 provider `ensure_connected`，允许空 adapter 在 provider 等待后恢复，再确认 connected；原 owner bridge 路由保持原通道。没有新增通用轮询或改变 Claude 登录策略。
- [x] **P2：归档后的迟到事件重建投影。** 已通过真实 `make_event_handler` 入口验证并在 bus delivery 写入投影前拒绝已归档会话的迟到事件。新 turn/会话生命周期事件仅在 provider 事实确认且归档策略允许时恢复；本地归档及保留归档策略不会被绕过。审批发布也检查归档状态，历史读取继续使用现有消息中心。

本批次验证：

- `python3 -m pytest -q tests/test_session_target_validation.py tests/test_provider_session_new.py tests/test_message_delivery_failures.py tests/test_events_streaming.py --tb=short`：87 passed。
- `python3 -m pytest -q tests/test_provider_owner_bridge.py --tb=short`：63 passed；3 项旧测试前提/路由兼容问题修正后执行同文件 `--lf --tb=short`，3 passed。
- 在 `mac-app` 执行 `node --test tests/sessionBrowserState.test.mjs tests/sessionNewComposer.test.mjs && npx tsc --noEmit`：26 passed，TypeScript 通过。
- `CARGO_HOME="$PWD/.onlineworker-local/cargo" cargo test --manifest-path mac-app/src-tauri/Cargo.toml --lib commands::task_board_state::tests --offline --quiet`：12 passed；IPC 用例使用测试所需的 Unix socket 权限运行。
- `git diff --check`：通过。源码回归覆盖真实事件入口和合成 provider，不代表真实 CLI/Telegram 或安装版 UAT 已完成。

## 2026-10-02 安装版自测

- `python3 scripts/sync-app-version.py --check` 与 `git diff --check` 通过；`CARGO_HOME="$PWD/.onlineworker-local/cargo" bash scripts/verify-packaged-fast.sh` 返回 0，重建 sidecar、生成 1.11.0 Apple Silicon DMG、更新包及签名，覆盖安装并确认新 App/主 bot 运行。没有以本地签名产物代替公开 updater 验收。
- 安装版 owner bridge 中 Codex、Claude 均返回 healthy；两者对不存在的合成会话发送及失效 question reply 均明确拒绝，共 4 项保护检查通过。
- 后续安装版 IPC 自测 6 项通过：既有合成会话的创建请求 ID 保留；活动流客户端主动断开重连后恢复 completed 状态与相同请求身份；重复历史 hydration 仍只有一条用户消息和一条助手回复；会话内容流客户端重连恢复完整快照且不重复；已存在会话的错误工作区发送在 provider 调用前拒绝；拒绝后原会话内容不变。此处是测试客户端断开重连，不代表 provider 进程故障、App 重启或积压恢复验收。
- 首轮桌面自测：新建草稿的空消息禁止发送、输入后允许发送通过；Codex 真实创建与首消息收发成功，但 pending 结束后详情区自动跳回旧会话。该缺陷已在下述追加修复中解决。
- **Codex 新建后选中项竞争：源码和安装版回归通过。** 已用真实 `MessageEventBus` 投影与前端状态函数确定性复现：首个 `session.recovery.updated` 带创建请求 ID，但 activity 仍是 `idle`；pending 认领匹配成功并清除 composer，`mergeLiveSessionActivities` 却过滤该状态，新 ID 尚不在列表中，选中项保护立即回退旧首项。现已让带有效创建请求 ID 的真实 activity 在 `idle` 至完成阶段保持可见；同步新建成功也先更新列表缓存，避免立即刷回旧缓存。归档行保持归档，移除 bus activity 后不凭请求 ID 保留已消失会话。
- 追加修复验证：在 `mac-app` 执行 `node --test tests/sessionBrowserState.test.mjs tests/sessionNewComposer.test.mjs && npx tsc --noEmit`，27 passed，TypeScript 通过；`git diff --check` 与 `python3 scripts/sync-app-version.py --check` 通过。
- 追加修复已执行 `CARGO_HOME="$PWD/.onlineworker-local/cargo" bash scripts/verify-packaged-fast.sh`，返回 0（94 秒），完成 1.11.0 重建、覆盖与重启。用户确认允许 Codex 测试及可能的完成通知后，通过原生安装版界面新建会话并发送纯文本标记：pending 自动切入真实新会话，流式回复、最终回复和手动刷新列表后始终保持该会话选中，助手准确返回合成标记 `SAMPLE-CODEX-SELECTION-CHECK`。没有重复发送或修改用户文件。
- 任务运行时，安装版 `prepare_app_update` 明确拒绝准入；没有创建备份或执行更新安装。
- 安装版点击检查更新显示真实失败。公开稳定 Release 缺少 `latest.json`（HTTP 404），因此在线新版本检测、下载、签名拒绝和安装恢复继续未验收。
- 后续验收范围按用户要求仅保留 Codex，Claude 真实发送与问答不再继续，也不标为通过。Telegram 交互验收仍跳过；真实 Codex question 回答及 provider 故障恢复场景未验收。此前自动审批拒绝的 Claude 首消息未发送。

## 2026-10-02 看板时间与最近结束规则

- 修复 Codex 启动恢复用当前时间发布旧消息的问题：启动事件使用原始记录的时间，历史 hydration 不再推进 activity 更新时间。`python3 -m pytest -q tests/test_codex_tui_realtime_mirror.py tests/test_message_event_bus.py tests/test_session_stream_recovery.py --tb=short`：64 passed。快速打包安装返回 0（108 秒）；安装版两条旧会话保持原历史日期，重载历史后时间不变。
- 按用户要求，“最近结束”只接收最近 7 天内 completed、未归档的会话，按更新时间倒序最多显示 5 条，计数与显示条数一致；关注状态不绕过该条件。需要处理和正在运行分组保持原有规则。
- 卡片和详情共用原生 `Intl.RelativeTimeFormat`，按秒、分钟、小时、天、周、月、年选择合适单位；无有效时间时显示未知。
- 修正结束卡片误用“关注中”的状态文案：卡片与详情共用状态判定，按真实执行状态显示需要处理、执行中、已完成或已中断，关注仅由星标表达。中英文文案同步；相同前端检查命令新增关注/未关注下的状态回归后为 39 passed，TypeScript 通过；1.11.0 快速打包、覆盖与重启返回 0（96 秒）。
- 在 `mac-app` 执行 `node --test --test-reporter=dot tests/taskBoard.test.mjs tests/taskBoardConversationRefresh.test.mjs tests/taskBoardQuestions.test.mjs && npx tsc --noEmit`：38 passed，TypeScript 通过；已覆盖 7 天边界、旧关注项、最多 5 条、排序与中英文时间格式。快速打包安装返回 0（96 秒）；安装版看板已过滤原有旧会话，显示“最近结束 0”和“最近 7 天没有结束的 Session”。

## 实施顺序与边界

优先处理异常恢复、桌面问题回答与通知失败补发，随后补会话搜索、账号生效反馈和发布易用性。STAB-07 是独立条件项，不作为其余补充工作的前置依赖。

- 复用 MessageEventBus、provider registry/adapter、owner bridge、AppStorage 与现有原子写入；状态和历史仍由消息中心统一提供。
- 恢复状态必须区分明确未发送、已发送、结果不确定、仅保存或绑定未完成。未知结果不自动重发，核实不能只依赖原文相等。
- UI、通知与搜索不另建 provider 会话读取链，不新增周期性轮询来维持消息显示。
- Provider 问题回答绑定真实请求；已处理、过期或仅镜像的请求不能被重新执行。审批继续遵守现有 app-server 权威和 thread topic 路由规则。
- 离线归档排队仍不属于当前范围；失败保持真实状态，并指引服务恢复后重试。
- 分别记录源码检查和获准的安装版验收，不将快速安装成功代替功能 UAT。

## DELIVERY-07：异常后的自助恢复

**现状：** 普通桌面发送已保存每个会话最近一次请求的 request id、完整原文、附件引用和发送阶段，沿用 AppStorage 原子写入及 MessageEventBus 投影。明确未发送可恢复到输入框后编辑、手动重试；已有草稿时不覆盖。附件失效会提示移除后重新选择。发送结果不确定时保留原请求并禁止重复提交；重新核实复用既有会话流和历史加载，不新增轮询或 transcript 读取链。新建会话既有恢复记录保持原有边界。

**已完成验证：**

- 发送前先保存恢复记录；保存失败不调用 provider。重复 request id 不再次发送；相同 ID 携带不同输入会被拒绝。
- 准备阶段失败标为未发送；进入 provider 发送后异常保守标为结果不确定。重启时 preparing 恢复为 failed，sending 恢复为 unknown，不自动重发。明确失败不阻止更新准入，不确定请求继续阻止更新。
- 普通恢复状态与新建恢复状态分离；完整原文与附件路径仅供会话内容投影使用，不写入公开事件摘要。历史读取失败的错误帧也能带回恢复记录。
- `python3 -m pytest -q tests/test_send_recovery.py tests/test_provider_owner_bridge.py tests/test_session_target_validation.py --tb=short`：84 passed。随后补充用例后执行 `python3 -m pytest -q tests/test_send_recovery.py tests/test_message_event_bus.py tests/test_provider_session_new.py tests/test_app_update.py --tb=short`：60 passed；最终增加历史不可读场景后，`python3 -m pytest -q tests/test_send_recovery.py --tb=short`：7 passed。
- 在 `mac-app` 执行 `node --test --test-reporter=dot tests/sessionAsyncBoundaries.test.mjs tests/sessionComposerAttachments.test.mjs tests/providerSessionEventStream.test.mjs tests/sessionNewComposer.test.mjs && npx tsc --noEmit`：12 passed，TypeScript 通过；最后调整错误帧恢复后单独执行 `tests/sessionAsyncBoundaries.test.mjs`：7 passed。
- `CARGO_HOME="$PWD/.onlineworker-local/cargo" cargo test --manifest-path mac-app/src-tauri/Cargo.toml --lib commands::provider_sessions::tests --offline --quiet`：22 passed。`git diff --check` 与 `python3 scripts/sync-app-version.py --check` 通过，版本 1.11.0。
- `CARGO_HOME="$PWD/.onlineworker-local/cargo" bash scripts/verify-packaged-fast.sh` 返回 0（88 秒），完成 sidecar 重建、打包、覆盖安装和重启。安装版 Codex 使用专用测试会话与缺失附件，在 provider 发送前明确失败；实际返回会话 ID 的总线快照保留原文、附件引用和失效原因。原生 App 显示恢复面板，点击后原文及附件恢复到输入框，已有输入时禁用恢复按钮。会话准备产生的两个测试会话均已归档，并核验归档标记持久化；没有向模型提交该测试正文。

### 2026-10-07 回执核实与新建等待恢复

- Codex `turn/start`、`turn/steer` 的精确 JSON-RPC 响应关联到原发送请求，持久化 request id、真实 thread id、turn id 和明确接收/拒绝结果。迟到响应保留给手动核实，不通过最新 turn、时间或相同文本认领送达。
- 新增共享的 `recheck_session_send` 操作，桌面经既有 Tauri/owner bridge 调用。它只核实已保留的回执和原请求，更新经 MessageEventBus 的恢复投影；没有创建或重发路径。核实接收后清除投递失败提示，消息内容和任务状态仍沿用权威总线链。
- 新建首消息的恢复记录进入同一个会话恢复面板；明确失败可恢复原文和附件，核实已返回真实 ID 的请求可打开原会话。新建等待可显式停止界面等待，原请求和 provider 任务保留，未知状态仍禁止重复发送。
- 创建尚未返回真实 ID 时，在既有 AppStorage 中保留工作区最近一条未解决创建请求。写入失败不调用创建；重启后结果不确定继续保留输入，不重复创建。得到真实 ID 后由既有会话恢复记录接管，不生成伪造的真实会话 ID。
- 首消息区分准备与实际发送阶段；准备失败明确未发送，实际发送中断为未知。原首消息未确认时，普通桌面发送也不能绕过保护；停止等待不解除该保护。
- `python3 -m pytest -q tests/test_send_recovery.py tests/test_provider_session_new.py tests/test_provider_owner_bridge.py tests/test_message_event_bus.py tests/test_app_update.py --tb=short`：首轮 120 passed，4 项行为/测试前提问题和 8 项 socket 权限失败；修正后同一组 `--lf --tb=short`：12 passed。最后调整恢复投影后执行 `python3 -m pytest -q tests/test_send_recovery.py tests/test_message_event_bus.py tests/test_provider_session_new.py --tb=short`：55 passed；补充旧客户端重复发送保护后，`python3 -m pytest -q tests/test_send_recovery.py --tb=short`：12 passed。
- `python3 -m pytest -q tests/test_codex_adapter.py tests/test_codex_runtime.py -k 'send_user_message or turn_steer or send_message or call_normalizes' --tb=short`：17 passed，78 deselected。
- 在 `mac-app` 执行 `node --test --test-reporter=dot tests/sessionAsyncBoundaries.test.mjs tests/sessionNewComposer.test.mjs tests/providerSessionEventStream.test.mjs`：13 passed；`npx tsc --noEmit`：通过。新增行为检查覆盖跨会话迟到核实不更新界面，以及停止等待不发送、不取消、不清除原请求。
- `CARGO_HOME="$PWD/.onlineworker-local/cargo" cargo test --manifest-path mac-app/src-tauri/Cargo.toml --lib commands::provider_sessions::tests --offline --quiet`：22 passed（临时 Unix socket 用例带所需权限）。`git diff --check` 与版本一致性检查通过，版本 1.11.0。
- 首轮快速打包、覆盖与重启返回 0（100 秒）。安装版主动关闭一条 Codex 合成请求的客户端而不读取响应后，重新核实找到了真实会话及匹配的请求/turn 回执，并准确收到标记 `SAMPLE-DELIVERY-RECHECK`。重启验收发现核实操作重复追加用户消息；已删除这次消息重放，核实只更新恢复投影，相关恢复用例 12 passed。修复版快速打包、覆盖与重启返回 0（96 秒）。安装版同一请求跨 App/bot 重启后仍保留原文及匹配的 thread/turn 回执；先加载历史，再连续两次核实，仍只有一条用户消息和准确的最终标记。本次唯一测试会话已归档并核验持久化标记，原历史保留。安装版模拟的是客户端丢失响应，app-server 原回执已收到；provider 连接断开且完全无回执、长时间新建等待按钮的安装版故障注入仍未验收，相关保守处理与停止等待行为已源码验证。

**剩余边界：** 每个会话只保留最近一次发送尝试，每个工作区只保留一条未解决创建请求；迟到 RPC 回调最多保留 128 条。连接断开且从未收到原 RPC 回执时，现有 Codex 接口没有按客户端请求 ID 回查结果的能力，不能确认送达或认领创建出的会话，继续显示未知并禁止重发。`codex queue` 没有可关联消息 ID，不能用于回执核实。不会以相同文本、最新 turn 或历史重放替代证据。

**验收：**

- [ ] 同步拒绝、后台失败、响应丢失和进程重启后，用户仍能找到原请求及真实会话；附件失效时给出重新选择提示。
- [ ] 使用 provider 提供的消息身份或状态核实发送结果；证据不足继续标为未知，不以文本相同自动确认送达。
- [ ] 明确未发送时允许用户确认重试；已发送时只补保存或绑定；未知状态不会自动发送第二份。
- [ ] 新建 pending 不会无限显示成功或等待；原请求与恢复操作不能因页面切换串入其他会话。

## DELIVERY-08：桌面 provider question 回答

**现状：** Task Board 已通过总线展示完整问题、选项和自定义输入，并经 owner bridge 回写真实 provider question；失效请求与 Telegram 等待状态的复审修复已通过源码检查，真实双端功能验收待完成。

**待补范围：** 通过 provider capability 和统一总线投影展示问题、选项或自由输入，并通过对应 adapter 回答同一真实请求。

**验收：**

- [ ] 支持的 provider question 在 App 中可完整展示并回答；不支持或仅镜像时明确说明可用处理入口。
- [ ] 回答进入原 question request 的协议回写，普通会话文本发送不能冒充问题回答。
- [ ] 重复点击、过期请求、已在 Telegram/CLI 回答和跨会话切换都有明确结果，不重复回写。

## DELIVERY-09：通知失败记录与补发

**现状：** 已有失败事件、局部网络重试和部分完成通知补发；缺少统一的未送达列表、人工补发入口和跨重启的待发送记录。

**待补范围：** 保留最小渠道投递记录，由总线派生未送达状态；先提供失败原因和显式人工补发。通知补发只发送通知，不重新执行 provider 任务、原始用户消息或审批决策。

**验收：**

- [ ] 失败通知按渠道显示原因和可用操作，重启后仍可找到未完成的投递；保留量有界。
- [ ] 补发关联原通知；已成功的渠道不被无意重复投递，响应不确定时不宣称已送达。
- [ ] 慢网络、补发与记录保存不阻塞本地会话投影；平台接受消息不被展示为用户已读。
- [ ] 不重放过期审批按钮，不把未绑定 topic 的审批补发到 workspace/global topic。

## DELIVERY-10：主 Sessions 关键词搜索

**现状：** 主会话页仅按 provider、工作区和 Active/Archived 筛选；Codex 会话资产页的局部搜索不能替代通用会话入口的查找。

**待补范围：** 在主 Sessions 入口搜索当前可见集合的标题、目录和近期摘要，兼容现有 provider、工作区与归档筛选。历史全文索引和独立搜索服务留待后续需求，不作为首版依赖。

**验收：**

- [ ] 内置 provider 使用一致的搜索入口，结果可直接打开对应真实会话。
- [ ] 关键词与现有筛选共同生效；实时更新、归档和无结果状态不会丢失当前选择或伪造会话。
- [ ] 使用消息中心和现有 provider facts 数据，不由搜索页面重读 transcript 或新增后台轮询。

## DELIVERY-11：账号 Apply 与会话生效反馈

**现状：** 账号页的 Apply 状态和“不重启进程”提示已实现；会话页尚不能说明当前连接是否已采用新凭据。

**待补范围：** 区分凭据已写入、provider 连接已确认和无法确认的状态，说明哪些连接或新操作受影响，以及必要时可执行的重连动作。实际账号事实由 provider 提供，不能按最近一次 Apply 推断所有会话都已切换。

**验收：**

- [ ] Apply 后显示影响范围及是否需要重连；无法确认的会话明确显示未知，不伪造生效状态。
- [ ] 账号信息不包含凭据原文；失败和回退仍保留先前有效状态。
- [ ] 不自动停止或重连运行中的任务；真实账号 mutation 验收单独取得明确授权，并衔接 Phase 23 的既有待验收项。

## DELIVERY-12：发布与升级易用性

**现状：** 已接入 Tauri updater 的检查、下载、签名校验、显式安装并重启，以及双架构 CI 与条件式 Apple 签名、公证。复审修复已通过源码检查与快速打包安装；安装版忙碌拒绝和检查失败提示已验证。公开发布端缺少 updater manifest，线上 updater、Intel 安装态及真实 Apple 签名、公证尚未验收。

**待补范围：** 完成 updater 实际用户路径验收。安装由用户显式触发，忙碌任务阻止安装；安装失败恢复旧包，重启后的健康检查和自动回滚不宣称已完成。

**验收：**

- [ ] 正确识别当前版本、新版本和网络失败；检查更新不自动安装，也不停止正在运行的任务。
- [ ] 条件具备后，CI 为声明支持的架构生成并验证实际可运行的产物；签名和公证结果有证据，凭据不进入仓库或日志。
- [ ] VERSION、应用配置、锁文件、tag 与产物版本一致，稳定包标识、签名身份和用户数据目录不被擅自迁移。

## 条件项：STAB-07 独立 Desktop owner 控制

将这项缺口纳入 Phase 25 补充跟踪，保留原 `deferred` 状态、解阻条件和验收标准，详见 [24-07-PLAN.md](../24-runtime-authority-and-durability-hardening/24-07-PLAN.md)。本次范围补充不代表已经取得独立 owner 控制能力。

- [ ] 支持的接口能发现并连接原 session owner，或目标会话从创建时即由 OnlineWorker 托管。
- [ ] 在真实 active-writer 会话中完成输入、真实 interrupt、commentary/final 回流，且不启动第二 writer。
- [ ] 同一可见消息只有一个权威来源；没有接口证据时继续标为受限，不以 mock 结果代替真实验收。

## 既有功能的待验收

- [ ] 25-02：安装版自动更新、重连快照及慢 IM/流积压恢复；真实 Telegram 网络恢复不以成功启动进程代替。
- [x] 25-03：安装版 Codex 真实新建、首消息收发和 pending 转真实会话后的选中项保持。
- [ ] 25-03：绑定失败、首消息不确定、发送后保存失败与恢复操作。
- [ ] 账号相关真实操作验收与 Phase 23 记录衔接；深色模式完整视觉验收仍归 Phase 22，不重复实现已有功能。

完成标准：新增范围分别有对应源码检查和真实用户路径验收；未执行或被明确豁免的项如实保留，不因创建补充文档或发布 tag 而标记完成。
