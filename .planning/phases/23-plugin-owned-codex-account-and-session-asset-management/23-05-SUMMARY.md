---
phase: 23-plugin-owned-codex-account-and-session-asset-management
plan: 05
subsystem: auth
tags: [codex, cockpit-tools, import, identity, redaction]

requires:
  - phase: 23-01
    provides: approved account feature implementation boundary
provides:
  - Cockpit-compatible object and array account parser/exporter
  - deterministic account identity, upsert, external classification, and redacted DTO
affects: [23-06, 23-07, 23-08, 23-10, 23-12]

tech-stack:
  added: []
  patterns: [raw credential preservation, mode-namespaced hashed identity]

key-files:
  created:
    - plugins/providers/builtin/codex/python/account_model.py
    - plugins/providers/builtin/codex/python/compat.py
    - plugins/providers/builtin/codex/tests/test_account_compat.py
    - plugins/providers/builtin/codex/tests/test_account_model.py
  modified: []

key-decisions:
  - "Supported imports retain the full raw JSON object so unknown top-level and nested fields survive export and upsert."
  - "Token, agentIdentity, and apikey identities use separate SHA-256 namespaces; list DTOs never include credentials."

patterns-established:
  - "External account parsing returns fixed per-item statuses and messages without echoing input values."
  - "Re-import deep-merges an existing record only when exactly one stable identity matches."

requirements-completed: [D-08, D-09, D-14, D-15, D-17, D-18, D-19, D-20, D-21, D-24, D-25]

duration: 13min
completed: 2026-08-17
---

# Phase 23 Plan 05: Codex 账号模型与 Cockpit 兼容格式 Summary

**Codex 插件现可独立解析和导出 Cockpit 三类账号格式，并以去敏稳定身份完成安全 upsert。**

## Performance

- **Duration:** 13 min
- **Started:** 2026-08-17T12:18:52Z
- **Completed:** 2026-08-17T12:31:40Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- 支持 top-level object/array、OAuth 结构输入和 local-file 复用 parser。
- 保持 token、agentIdentity、apikey 三种 Cockpit shape 与未知字段完整 round-trip。
- 实现 hashed stable identity、唯一命中更新、歧义保护、external matched/unmanaged 与 secret-free DTO。

## Task Commits

1. **Task 1: 先建立 Cockpit shape 与 identity/upsert fixtures** - `9a7d7f1` (test)
2. **Task 2: 实现 Codex 独立 compat/model** - `fde5252` (feat)

**Plan metadata:** 本提交

## Files Created/Modified

- `plugins/providers/builtin/codex/python/account_model.py` - 稳定 identity、upsert、external 分类和去敏 DTO。
- `plugins/providers/builtin/codex/python/compat.py` - bounded JSON parser、三类 credential 校验和 Cockpit array export。
- `plugins/providers/builtin/codex/tests/test_account_compat.py` - object/array/mode/unknown-field fixtures。
- `plugins/providers/builtin/codex/tests/test_account_model.py` - identity/upsert/redaction/external fixtures。

## Decisions Made

- 不复制 Cockpit 源码；只根据固定 commit 的格式事实实现独立 parser。
- `agentIdentity` 身份包含 account、chatgpt user 与 runtime，且不伪造 access token。

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- 23-06 可直接加密 `AccountRecord.credentials`，明文索引只消费 redacted DTO。
- 23-07/23-08 可复用同一 parser/model，保持 import 与 Apply 分离。

## Verification

- `python3 -m pytest plugins/providers/builtin/codex/tests/test_account_compat.py plugins/providers/builtin/codex/tests/test_account_model.py -q` — 8 passed
- `python3 -m py_compile plugins/providers/builtin/codex/python/account_model.py plugins/providers/builtin/codex/python/compat.py` — passed
- `git diff --check` — passed

## Self-Check

PASS

---
*Phase: 23-plugin-owned-codex-account-and-session-asset-management*
*Completed: 2026-08-17*
