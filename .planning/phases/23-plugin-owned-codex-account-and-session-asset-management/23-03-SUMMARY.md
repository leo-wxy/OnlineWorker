---
phase: 23-plugin-owned-codex-account-and-session-asset-management
plan: 03
subsystem: plugins
tags: [tauri, sidecar, capabilities, loopback, security]

requires:
  - phase: 23-02
    provides: independent builtin account feature discovery
provides:
  - runtime-free account feature list/action sidecar entry
  - generic Tauri browser, loopback, and one-use native file capabilities
  - host-derived per-feature data roots and redacted response envelopes
affects: [23-04, 23-07, 23-09, 23-10, 23-11, 23-12]

tech-stack:
  added: []
  patterns: [early one-shot bootstrap, opaque trusted context, bounded native capabilities]

key-files:
  created: []
  modified:
    - core/account_features.py
    - main.py
    - tests/test_account_features.py
    - mac-app/src-tauri/src/commands/account_feature.rs
    - mac-app/src-tauri/src/commands/mod.rs
    - mac-app/src-tauri/src/lib.rs

key-decisions:
  - "Rust 只调用 Python account-feature one-shot，不解析 manifest 或 Codex action。"
  - "原生文件路径只经 feature/mode/expiry-bound one-use handle 注入 trusted context。"
  - "Sidecar stdin/stdout、loopback request 和 callback result 都有固定上限与过期清理。"

patterns-established:
  - "Account feature bootstrap 在 Telegram/bot/state/lifecycle import 前输出单一 JSON envelope 并退出。"
  - "Tauri capability errors 使用固定脱敏文案，不返回 stderr、callback query 或真实路径。"

requirements-completed: [D-01, D-02, D-03, D-04, D-05, D-07, D-37, D-40]

duration: 33min
completed: 2026-08-17
---

# Phase 23 Plan 03: 中性账号功能宿主 Summary

**账号插件现在可在 Provider runtime、app-server 与消息链路之外独立发现并执行一次性本地 action。**

## Performance

- **Duration:** 33 min
- **Started:** 2026-08-17T12:45:38Z
- **Completed:** 2026-08-17T13:18:10Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments

- 在 live runtime import 前增加 stdlib-only feature list/action bootstrap，并保持唯一 Python discovery source。
- 建立 opaque Tauri transport、host 派生的 0700 data root、系统浏览器与一次性 open/save capability。
- loopback 只监听 `127.0.0.1`，限制 path/request/deadline，单消费者读取并自动清理结果。
- sidecar stdin 写入移出 async worker，stdout/stderr 使用 raw chunks、总量上限、超时 kill 与固定脱敏 envelope。

## Task Commits

1. **Task 1: 先锁定账号功能宿主边界** - `0c0d254` (test)
2. **Task 2: 实现中性账号功能宿主** - `1787075` (feat)

**Plan metadata:** 本提交

## Files Created/Modified

- `core/account_features.py` - 保存已验证 backend entry 与打包态模块名。
- `main.py` - early one-shot list/action dispatcher。
- `tests/test_account_features.py` - runtime-free discovery/action subprocess 契约。
- `mac-app/src-tauri/src/commands/account_feature.rs` - generic process、data root、file/browser/loopback capabilities 及 Rust 测试。
- `mac-app/src-tauri/src/commands/mod.rs`、`mac-app/src-tauri/src/lib.rs` - 注册中性 Tauri commands 与 host state。

## Decisions Made

- 只复用现有 sidecar process/output shape；不复用 provider owner/session authority。
- Save capability 绑定用户选择的 pathname 与 canonical parent；不强绑目标 inode，以保留原子替换写入语义。
- PyInstaller 通过既有 `collect_submodules` 加载 builtin Python backend；frontend/icon 打包数据留给 23-04/23-10 同 manifest 启用时接入。

## Deviations from Plan

- 同步扩展 `core/account_features.py`，让 one-shot action 从唯一 discovery 结果取得 validated backend，而不是在 `main.py` 建第二套路径解析。

## Issues Encountered

- 独立复核发现默认 line-buffered shell output 会在宿主限流前缓存无换行大输出；改为 raw chunks 后由宿主执行 8 MiB 总量限制。
- loopback 初版只限制 accept 循环；补充 request absolute deadline，慢连接不能越过 session TTL。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- 23-04 可直接把 descriptor 映射到 builtin frontend registry。
- 23-07/23-09 可复用 browser、loopback 与 native file handles；23-06 仍需安装已批准但当前环境缺失的 `cryptography==48.0.1` 才能完成真实验证。

## Verification

- `python3 -m pytest tests/test_account_features.py tests/test_main.py tests/test_provider_facts.py -q` — 40 passed
- `cargo test --manifest-path mac-app/src-tauri/Cargo.toml account_feature --lib` — 9 passed
- `python3 -m pytest tests/test_packaging_socks_support.py -q` — 6 passed
- `cargo fmt --manifest-path mac-app/src-tauri/Cargo.toml --check` — passed
- `git diff --check` — passed
- Build/package/install/restart/launch — not run, per repository boundary.

## Self-Check

PASS

---
*Phase: 23-plugin-owned-codex-account-and-session-asset-management*
*Completed: 2026-08-17*
