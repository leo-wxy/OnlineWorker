# Phase 23 Pattern Mapping

> 这份文件只记录当前仓库的真实 analog、可复用边界和核验 anchors。下面的
> Phase 23 路径是规划角色图，不表示文件已经存在；Codex 业务仍必须留在
> `plugins/providers/builtin/codex/`，host 不按 provider ID 写分支。

## 结论先行

- **可直接复用**：现有 manifest/YAML 读取、插件失败隔离的形状；`default_codex_home()` 的有效 Home precedence；`data_dir()`/`ensure_data_dir()` 的宿主数据根；现有 `ow-*` CSS、native dialog、pytest/Rust/Node test 基础设施。
- **需最小扩展**：在当前 discovery 旁增加中性 account-feature metadata；增加独立常驻 opaque action worker；`App.tsx` 增加动态入口和 selector/page mount；Codex builtin 通过 build-time frontend entry 接入。
- **禁止复用**：`provider_owner_bridge`、`provider_sessions`、Task Board、EventBus、notification、现有 Usage/ccusage projection、Codex app-server/runtime lifecycle。它们把离线页面重新耦合到 runtime 或实时链路，违反 D-02/D-12/D-26/D-31/D-40。

## 角色与真实 analog

| 计划角色 | 当前真实 analog（符号 / 精确 anchor） | 观察到的结构与复用判断 |
| --- | --- | --- |
| provider manifest / descriptor / capability | `core/providers/contracts.py:68-80` `ProviderManifestCapabilities`；`:93-106` `ProviderMetadata`；`:173-189` `ProviderDescriptor`；`core/providers/manifest.py:85-100` `capabilities_from_manifest()`、`:112-173` `metadata_from_provider_manifest()`；`plugins/providers/builtin/codex/plugin.yaml:1-12,33-58,139-142`；`plugins/providers/builtin/codex/python/provider.py:61-79` `create_provider_descriptor()` | **需最小扩展**：沿 YAML 解析、稳定 id/label/icon/entrypoint 的现有形状新增中性 feature declaration/descriptor。**不要**把 account/page 字段塞进 `ProviderManifestCapabilities`；该类型目前全是 runtime/session/message 能力。Codex descriptor 的 hooks 从 `provider.py:67-127` 进入 live runtime，不能挂载 account actions。 |
| discovery / registry / per-plugin failure isolation | `core/providers/registry.py:19-27` `_iter_provider_plugin_manifests()`；`:37-48` `_load_descriptor_from_entrypoint()`；`:51-86` `_load_provider_descriptors()`；`:89-90` `provider_load_failures()`；`mac-app/src-tauri/src/commands/config_provider.rs:730-762,837-862` manifest source discovery | **可直接复用形状，需最小扩展边界**：复用 manifest path/import-root/校验/失败记录的思路；独立输出 feature metadata，不把 feature loader 塞入 `_PROVIDERS` live descriptor。失败应保留 feature id、entrypoint、safe diagnostic，不能让一个插件阻断其他 selector。Rust 的 `provider_plugin_manifest_sources_with_paths()` 可借鉴 builtin/overlay/fallback 顺序，但不要为 page runtime 误用 `provider_assets.rs` 的 provider-only include。 |
| generic account-feature worker | `main.py` early account-feature bootstrap；`plugins/providers/builtin/codex/python/tui_host_protocol.py:30-49` newline JSON encoding analog | **已最小扩展**：独立 early JSONL worker 串行处理 request-bound list/action；action/payload 对 host opaque。不得把 Phase 23 action 加进 provider session operation 列表，或让 worker 初始化 Telegram/provider runtime。 |
| Tauri command / worker lifecycle / timeout | `mac-app/src-tauri/src/commands/account_feature.rs` `AccountFeatureHostState` / `run_account_feature_worker()` | **已最小扩展**：Tauri 自持独立 child/stdin/stdout，限制输入输出与 timeout；异常时清理并在下一请求懒启动，不复用 owner bridge socket、provider session error 或 app-server authority。 |
| JSON envelope / generic error | `main.py:99-101,188-203` 输出 JSON；`provider_sessions.rs:762-777` 只在成功 stdout 反序列化 `Value`；`mac-app/src-tauri/src/commands/task_board_state.rs:90-120` 的 `ok/error` response structs | **需最小扩展**：host-visible response 只允许 `{ok,data,error{code,message,retryable,diagnosticId?}}` 等无 secret envelope；成功 data 由 plugin opaque 返回。`TaskBoard` response 可借鉴 optional error 字段和 serde camelCase，但不能复用其 activity/session contract。stdout 必须是唯一机器响应，stderr/diagnostic 不得含 credential/session 原文。 |
| App dynamic sidebar / page shell | `mac-app/src/App.tsx:70-80` `activeTab`/mount state；`:217-230` `getTabIcon()`；`:299-337` `PRIMARY_APP_TABS.map()` sidebar；`:440-545` `Suspense`/page mount；`mac-app/src/utils/appTabs.js:1-6` static tab registry；`mac-app/tests/appShell.test.mjs:10-23,59-85` shell contracts | **需最小扩展**：保留 `App` 的 sidebar width 84/248、native button、`Suspense` loading、page frame；新增的是“至少一个 account feature 才显示一个账号入口”、metadata-driven selector/mount 和 isolated error boundary。`PRIMARY_APP_TABS` 是静态主导航，不能把 Codex 硬编码进数组；feature presence 应来自 generic discovery。不要把 Codex labels/actions/model 放 `App.tsx`、`appTabs.js` 或 shared i18n。 |
| provider metadata-driven selector/card | `mac-app/src/components/ProviderSettingsPanel.tsx:146-207` `ProviderSettingsPanel` load/state；`:381-447` loading/error/empty + metadata map/card；`mac-app/src/components/ai-settings/AiSettingsSidebar.tsx`（metadata list/sidebar analog） | **可直接复用 UI 结构，需最小扩展数据契约**：`useState` 的 `loading/error`、`invoke`、`useCallback(load)`、metadata-driven `map` 和 per-id busy state 可复用。ProviderSettings 的 provider-specific capability checks、CLI auth fields、`externalCli` 分支不复用到 account host；Codex content 应留在 plugin entry。 |
| `ow-*` page/list/state styles | `mac-app/src/index.css:182-244` `.ow-page-frame`, `.ow-page-frame-soft`, `.ow-toolbar`, `.ow-segment`, `.ow-btn`, `.ow-btn-primary`；`:246-300` `.ow-badge`/alerts；`:308-322` `.ow-modal-backdrop`/`.ow-modal-panel` | **可直接复用**：UI-SPEC 要求的 panel/toolbar/modal/focus/semantic tokens 已存在；不要新增 UI 库、字体、全局 token 或硬编码颜色。注意 `.ow-modal-backdrop` 当前复用语义渐变，不要为插件新增渐变。 |
| modal / focus / cancel | `mac-app/src/components/ActionGuideDialog.tsx:37-57` focus restore + Escape；`:72-83` portal/dialog semantics；`:143-159` disabled primary/footer；`mac-app/src/components/LogWindow.tsx:91-99` backdrop click stopPropagation、`:132-151` close controls | **可直接复用**：`role="dialog"`, `aria-modal`, labelled title/description、Escape、initial focus/focus restore、portal、native `disabled`。Add-account modal 只保留 OAuth 与 Token / JSON 两个 tab，并保留错误输入；不复制 ActionGuide 的 command-copy 业务或 LogWindow 的 live log stream。save-dialog cancel 应沿 `support_bundle.rs:870-889` 的 `Ok(None)` 静默语义。 |
| state panel / loading / retry / background refresh | `mac-app/src/components/session-browser/presentation.tsx:80-106` `StatePanel`；`navigation.tsx:100-105,271-275` 只在空列表时显示 loading/empty；`mac-app/src/pages/SessionBrowser.tsx:274-329` per-provider loading/retry bookkeeping；`mac-app/src/components/MaintenanceSettingsPanel.tsx:281-326` `aria-live` + expandable diagnostics | **可直接复用结构，最小改文案**：保留 populated rows during refresh（不要用全屏 loading 清空）、`aria-live="polite"`、error/warning tone、retry/diagnostic toggle、native disabled。`StatePanel` 的 `getProviderUi()` provider color mapping 不应带入 account host；host 只使用 feature metadata/icon/label。 |
| checkbox/list/expandable rows | `mac-app/src/pages/CommandRegistry.tsx:255-284` native checkbox + per-row disabled busy；`:349-448` toolbar/search/segmented filters；`:464-489` list loading/no-results/map；`mac-app/src/components/session-browser/navigation.tsx:282-372` row sibling action buttons and keyboard handling | **需最小扩展**：复用 checkbox selection、search filtering、scoped batch actions、row metadata、disabled while mutation。Session asset row 必须按 UI-SPEC 用非交互 wrapper，checkbox/disclosure/action 为 sibling native controls；不要照搬现有 `role="button"` session wrapper 的 nested actions 结构。 |
| Codex effective home | `plugins/providers/builtin/codex/python/transport.py:25-27` `default_codex_home()`；`:35-53` endpoint resolution也调用该 helper | **可直接复用纯 helper**：有效路径优先非空 `CODEX_HOME`，否则 `~/.codex`。新 action 必须一次解析并显式传 `home` 到所有 read/write/scan；测试注入 temp home。不要复用 transport 的 socket/app-server functions。 |
| Codex session/index parser | `plugins/providers/builtin/codex/python/storage_runtime.py:15-32` visibility filter；`:87-126` JSONL collection/cache；`:129-225` `session_meta`/preview/timestamps；`:271-312` index merge；`tests/test_storage_extended.py:13-23,25-145,148-188` temp JSONL fixtures/assertions | **需最小扩展/先修参数化**：纯 parser/visibility/JSONL merge 可缩小后复用；当前 `storage_runtime.py:11-12,35-55,228-250` 仍写死 `~/.codex/sessions`、`~/.codex/session_index.jsonl`、`state_5.sqlite`，禁止原样复用。Session page 应在 Codex plugin 内使用 effective-home 参数，不接 OnlineWorker Sessions projection。 |
| local 30-day usage algorithm | `plugins/usage/builtin/ccusage/python/runtime.py:38-55` Codex roots；`:111-147` JSON summary；`:150-165` cache | **禁止复用 projection/sidecar seam**：它属于 Usage plugin、`source_id`/ccusage sidecar/cache，违反 D-31。只可作为“本地文件、成本 unavailable 而非伪造 0”的行为参考；实现必须归 Codex plugin，并独立于 `get_usage_source_*`。 |
| atomic JSON write / temporary file | `core/storage.py:121-161` `load_storage()`/`save_storage()` temp + `os.replace`；`plugins/providers/builtin/codex/python/hook_bridge.py:145-150` `_atomic_write_text()`；`plugins/providers/builtin/codex/python/tui_host_protocol.py:90-108` same-directory `mkstemp` + replace；`mac-app/src-tauri/src/commands/task_board_state.rs:268-293` temp + rename | **可直接复用思路，需最小安全扩展**：same-directory temp + replace 是现有惯例；Phase 23 还必须 fsync（平台允许）、0600、bounded backup、恢复旧字节/current marker、并发锁和失败清理。现有 helpers 没有完整 backup/permission/rollback，不可声称直接满足账户安全 contract。 |
| plugin data dir / app data root | `config.py:66-87` `get_data_dir()`/`default_data_dir()`/`set_data_dir()`；`mac-app/src-tauri/src/commands/config.rs:17-60` `app_name()`, `data_dir()`, `ensure_data_dir()`；`mac-app/src-tauri/src/commands/attachment_cache.rs:52-60,103-109` per-feature subdir helper | **可直接复用 root resolution**：host 传 app data root，Codex plugin 在其 own subdirectory 管理 index/key/details/session-trash。`attachment_cache` 的“feature-owned subdir + explicit stats”是目录隔离 analog。禁止使用 Cockpit `~/.antigravity_cockpit`、真实 `~/.codex` 作为 plugin store，禁止把 `task_board_state.json`/usage/cache 当账号 datastore。 |
| native browser/file/save capability | `mac-app/src-tauri/src/commands/support_bundle.rs:860-889` `choose_support_bundle_path()`、cancel handling；`:928-955` save flow；`mac-app/src-tauri/src/commands/terminal.rs:126-173` generic open command | **可直接复用通用能力**：选择文件、save path、open browser/terminal 只做系统 capability，cancel 返回 `None`/静默；不得把 Codex auth/session vocabulary 放进通用 command。OAuth callback/state、JSON/ZIP validation 和 all business actions 必须由 Codex plugin owned backend 处理。 |
| pytest fixtures / tempdir guard | `tests/conftest.py:9-24` autouse `tmp_path`/temporary data dir isolation；`tests/test_provider_facts.py:220-275,278-377` manifest/descriptor contract、overlay success/failure isolation；`tests/test_storage_extended.py:25-145,148-230` real temp JSONL fixtures | **可直接复用**：现有 pytest + `tmp_path`/`monkeypatch`；Phase 23 新增 `plugins/providers/builtin/codex/tests/` 并显式 guard effective home/plugin data dir，不读真实 `~/.codex`/Trash/data dir。沿 provider failure isolation assertions 写 feature isolation，但不要把测试塞进 provider runtime tests。 |
| Rust tests / contract serialization | `mac-app/src-tauri/src/commands/provider_bridge_common.rs:256-293` timeout/process-tree tests；`command_registry.rs:912-940,1231-1315` private helper contract + temp-dir roundtrip；`attachment_cache.rs:269-355` temp data dir and source-boundary test | **可直接复用**：`#[cfg(test)]` private helper tests、`serde_json::json!` envelope assertions、temp directory cleanup、timeout injection。新增 `account_feature` tests 应覆盖 discovery/duplicate isolation/opaque action/error redaction/capability cancel；不要调用 real home 或 spawn packaged app。 |
| Node `node:test` / frontend source contract | `mac-app/tests/appTabs.test.mjs:10-30` static navigation contract；`appShell.test.mjs:10-85,107-148` sidebar/page/state source assertions；`commandRegistryView.test.mjs:19-67` metadata-driven provider views；`providerSessionSingleFlight.test.mjs:8-38` concurrency contract | **可直接复用**：Node builtin test runner、`readFileSync` source contract、metadata-driven fixture arrays、single-flight pattern。新增 `accountFeatureHost.test.mjs` / `accountFeatureCodex.test.mjs` 应断言 no-feature hidden/one generic entry/loading disabled/error isolation/opaque mount/secret-free DTO；不依赖 installed app 或真实 credentials。 |

## 禁止复用边界（按原因核验）

| 禁止 analog | 证据 | 为什么禁止 |
| --- | --- | --- |
| provider owner bridge / live session bridge | `core/provider_owner_bridge.py:14-30,44-48` imports state, routing and publishes messages；`mac-app/src-tauri/src/commands/provider_bridge_common.rs:84-86` socket；`provider_sessions.rs:347-486,723-777` owner-bridge session list/read/archive/sidecar | 依赖 runtime readiness、socket、session lifecycle；bot/provider runtime 停止时不可用。Phase 23 action 必须使用独立 account-feature worker。 |
| Task Board / EventBus / notification | `mac-app/src-tauri/src/commands/task_board_state.rs:20-68,90-154` session activity/control schema；`core/provider_owner_bridge.py:25-30` publish hooks | account apply/import/trash/repair 不得产生 live activity、message、notification 或 approval；这些结构会把离线资产操作带入实时链路。 |
| OnlineWorker Usage / ccusage projection | `mac-app/src-tauri/src/commands/provider_usage.rs:10-13,17-31,83-114` catalog/summary contracts；`plugins/usage/builtin/ccusage/python/runtime.py:111-165` sidecar/cache | Usage source/plugin ownership与 Codex 本地 session asset scope不同；复用会违反 D-31，且成本/数据根不再由 Codex feature 控制。 |
| `ProviderSettingsPanel` provider-specific fields | `ProviderSettingsPanel.tsx:65-84,417-438` external CLI/remote proxy capability branches | 可以复用 loading/card shell，不能复用 provider CLI auth/remote-proxy model；account host 必须 metadata-only。 |
| `provider_assets.rs` runtime include for page | `mac-app/src-tauri/src/commands/config_provider/provider_assets.rs:1-20,42-69` only manifest/icon/notification guide; `config_provider.rs:837-855` fallback | 该资源链只支持 YAML/icon/guide，不会让 Vite runtime 编译 TSX。页面应使用 builtin build-time frontend entry；禁止 iframe/WebView/host Codex include。 |

## 规划文件图（角色图，不是已存在文件）

```text
plugin.yaml
  └─ generic feature declaration
     ├─ neutral discovery/registry (core boundary, metadata + isolated failures)
     ├─ Tauri account_feature command
     │   └─ resident worker JSONL envelope (opaque featureId/action/payload)
     └─ App.tsx host
         ├─ dynamic single 账号 sidebar entry
         ├─ generic plugin selector + error/retry/diagnostic boundary
         └─ build-time frontend entry mount
             └─ plugins/providers/builtin/codex/frontend/
                 ├─ account overview/add modal/apply/export
                 └─ session asset page/search/ZIP/trash/repair

Codex feature backend (same plugin boundary)
  ├─ account_feature.py  -> opaque action dispatch
  ├─ account_model.py / compat.py -> identity + Cockpit shape + unknown fields
  ├─ account_store.py -> key/index/encrypted detail/atomic backup
  ├─ oauth.py -> PKCE/state/browser/callback
  ├─ apply.py -> one effective home/auth.json transaction
  └─ session_assets.py (+ optional session_package.py)
       -> local parser/30d summary/ZIP/conflict/trash/visibility repair

Tests
  ├─ plugins/providers/builtin/codex/tests/ (temp-only Python)
  ├─ mac-app/src-tauri/src/commands/account_feature.rs #[cfg(test)]
  └─ mac-app/tests/accountFeatureHost.test.mjs + accountFeatureCodex.test.mjs
```

## 10 个最关键 anchors

1. `core/providers/contracts.py:68-80` — 现有 runtime capability，不要把 account/page capability 混入。
2. `core/providers/registry.py:51-90` — manifest descriptor 加载、失败隔离、diagnostic 形状。
3. `plugins/providers/builtin/codex/plugin.yaml:139-142` — Codex 当前 Python entrypoints；feature entry 应独立声明。
4. `main.py` early account-feature branch — 独立 JSONL worker，不加载 live runtime。
5. `mac-app/src-tauri/src/commands/account_feature.rs` — Tauri 自持 worker/spawn/timeout/request binding，不带 owner socket 语义。
6. `mac-app/src/App.tsx:299-337,440-545` — sidebar/page mounting 的唯一 host seam。
7. `mac-app/src/components/ActionGuideDialog.tsx:37-83,143-159` — modal Escape/focus/ARIA/disabled 基础。
8. `plugins/providers/builtin/codex/python/transport.py:25-27` — `CODEX_HOME` precedence；必须一次解析并显式传递。
9. `plugins/providers/builtin/codex/python/storage_runtime.py:129-225,271-312` — 可提炼的 JSONL/session parser，同时暴露硬编码 home 风险。
10. `core/storage.py:144-161` + `tests/conftest.py:9-24` — atomic replace 思路与 temp-dir 测试隔离基线；Phase 23 需补 fsync/0600/backup/rollback。

## 未覆盖 / 存疑

- 当前仓库没有现成 AES-256-GCM、ZIP session package 或 account-feature frontend entry；`mac-app/src-tauri/Cargo.toml:26-38` 与 `requirements.txt:1-9` 均未提供可直接复用的 AES primitive。该依赖/放置仍需计划阶段明确，不能假设 stdlib 已满足。
- `storage_runtime.py` 的 session parser 可复用的纯部分已定位，但 `session_index.jsonl`/SQLite/archived visibility 的完整迁移语义需要按 `23-RESEARCH.md` 的 Cockpit commit-pinned 行为继续逐项实现和测试；本 mapping 不替代该行为核验。
- 当前 Tauri bundled `provider-plugins` 只支持运行时资源 staging；frontend overlay 的 build-time staging 尚无现成 analog。Phase 23 只覆盖仓内 builtin Codex entry，不应在本阶段设计通用 runtime JS loader。
