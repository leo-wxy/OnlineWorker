---
phase: 23-plugin-owned-codex-account-and-session-asset-management
plan: 02
subsystem: plugins
tags: [manifest, discovery, containment, pytest]

requires:
  - phase: 23-01
    provides: approved generic plugin frontend boundary
provides:
  - enabled-builtin account feature discovery
  - canonical entry containment and isolated safe diagnostics
affects: [23-03, 23-04, 23-10, 23-12]

tech-stack:
  added: []
  patterns: [runtime-free manifest discovery, fixed-code diagnostics]

key-files:
  created:
    - core/account_features.py
    - tests/test_account_features.py
  modified:
    - core/providers/manifest.py

key-decisions:
  - "Account feature discovery independently scans enabled builtin manifests and never imports provider registry/runtime."
  - "Overlay account frontends are diagnosed as unsupported and never become selectable."

patterns-established:
  - "Feature entries are existing manifest-relative files whose canonical paths stay inside the plugin directory."
  - "Host-visible failures contain only featureId and a fixed code."

requirements-completed: [D-01, D-03, D-04, D-05, D-06, D-07, D-37]

duration: 13min
completed: 2026-08-17
---

# Phase 23 Plan 02: 中性账号插件发现契约 Summary

**独立发现 enabled builtin 账号功能，并在不加载 Provider runtime 的前提下隔离不安全 manifest。**

## Performance

- **Duration:** 13 min
- **Started:** 2026-08-17T12:18:52Z
- **Completed:** 2026-08-17T12:31:40Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- 增加六字段中性 `AccountFeatureDescriptor` 和确定性 builtin discovery。
- 拒绝绝对路径、父目录、分隔符、缺失文件与 symlink escape。
- 固定安全诊断，且 overlay、坏 manifest、重复 feature 不影响合法 feature。

## Task Commits

1. **Task 1: 先锁定中性 discovery 行为** - `23ec005` (test)
2. **Task 2: 实现独立 builtin manifest feature loader** - `cd925ed` (feat)

**Plan metadata:** 本提交

## Files Created/Modified

- `core/account_features.py` - 中性发现、校验与诊断。
- `core/providers/manifest.py` - 无副作用 YAML mapping helper。
- `tests/test_account_features.py` - enabled/disabled、隔离、路径与 import graph 覆盖。

## Decisions Made

- 只复用现有 YAML/overlay 文件发现能力，不复用会初始化 `_PROVIDERS` 的 registry。
- backend entry 只校验文件，不在 discovery 时 import。

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- 红测 helper 最初创建了应缺失的 fixture 文件；修正 fixture 后行为测试通过。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- 23-03 可将 descriptor 暴露给一次性 host transport。
- 23-04 可按同一 metadata contract 挂载 builtin frontend。

## Verification

- `python3 -m pytest tests/test_account_features.py -q` — 4 passed
- `python3 -m pytest tests/test_provider_facts.py -q` — 20 passed
- `git diff --check` — passed

## Self-Check

PASS

---
*Phase: 23-plugin-owned-codex-account-and-session-asset-management*
*Completed: 2026-08-17*
