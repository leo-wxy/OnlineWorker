# Phase 20: One-Click Diagnostics And Support Bundle — Specification

**Created:** 2026-07-11
**Ambiguity score:** 0.08 (gate: ≤ 0.20)
**Requirements:** 6 locked

## Goal

Users can run bounded local health checks and export a privacy-safe support ZIP from Settings within 30 seconds, including when the managed bot is stopped or individual checks fail.

## Background

OnlineWorker already exposes Dashboard health, managed-service state, provider readiness, owner-bridge runtime status, plugin metadata, and log viewing. Troubleshooting still requires manually combining those sources. No reusable diagnostic report, redaction boundary, or support-bundle export exists.

## Requirements

1. **Independent diagnostics**: Each check returns `pass`, `warning`, or `fail`, a stable id, summary, optional detail/remediation, and duration; one failed or timed-out check does not abort the report.
2. **Existing truth reuse**: Version, service, provider, bridge, configuration, plugin, socket, and recent-log checks reuse current runtime/config boundaries instead of inventing parallel status rules.
3. **Bot-independent baseline**: App version, installation, configuration presence/parseability, plugin inventory, socket presence, and recent-log checks still run when the bot or owner bridge is unavailable.
4. **Sanitized support bundle**: Export contains a text summary, JSON report, sanitized config shape, provider/plugin inventory, bounded recent log excerpt, and manifest; it never copies original config, env, Session, transcript, or history files.
5. **User-controlled local export**: Export uses a native save location, creates a ZIP locally, returns its path/size/time, and can reveal the file in Finder. It performs no upload.
6. **Maintenance UI**: Existing Settings → Maintenance shows run progress, grouped results, copy-summary, export, and reveal actions without adding a top-level Tab.

## Boundaries

**In scope:** bounded Tauri checks, shared redaction, local ZIP generation, native save/reveal, Maintenance UI, Chinese/English copy, automated tests, installed-app smoke.

**Out of scope:** automatic repair or restart; automatic or assisted upload; full Session messages/prompts; Codex/Claude transcript/history reads; Keychain reads; persistent diagnostic telemetry; a new navigation Tab.

## Constraints

- Whole diagnostic run has a 30-second ceiling; bridge/provider checks use shorter per-check timeouts.
- Recent log inclusion is capped at 2 MiB before redaction.
- Partial results remain exportable.
- The implementation is macOS-installed-app-first and adds no new dependency when native system save/archive/reveal facilities are sufficient.

## Acceptance Criteria

- [ ] Diagnostics return stable independent results when all services are healthy.
- [ ] Bot stopped, missing socket, invalid config, missing log, and timed-out bridge produce partial reports rather than command failure or white screen.
- [ ] Support ZIP contains only the documented generated files and a manifest.
- [ ] Tests prove representative token, API key, authorization header, Telegram token, home path, and secret config values do not appear in generated artifacts.
- [ ] Tests prove Session prompts, assistant messages, JSONL transcripts, `.env`, and raw `config.yaml` are never copied.
- [ ] Concurrent run/export clicks are coalesced or disabled and do not create overlapping work.
- [ ] Installed app can save a ZIP, report its size/path, and reveal it in Finder.
- [ ] No network request, automatic repair, service restart, or configuration mutation occurs.

## Edge Coverage

**Coverage:** 7/7 applicable edges resolved · 0 unresolved

| Category | Requirement | Status | Resolution / Reason |
|----------|-------------|--------|---------------------|
| empty | R4 | ✅ covered | Missing log/config produces manifest entry and partial bundle |
| malformed | R2 | ✅ covered | Invalid YAML is a failed check; raw content is excluded |
| timeout | R1 | ✅ covered | Per-check timeout returns failure and report continues |
| unavailable dependency | R3 | ✅ covered | Bot/bridge absence preserves Tauri-owned checks |
| volume | R4 | ✅ covered | Log input capped at 2 MiB |
| concurrency | R6 | ✅ covered | UI disables/coalesces overlapping work |
| filesystem | R5 | ✅ covered | Cancelled/failed save returns no success state and no upload |

## Prohibitions (must-NOT)

**Coverage:** 5/5 applicable prohibitions resolved · 0 unresolved

| Prohibition (must-NOT statement) | Requirement | Status | Verification / Reason |
|----------------------------------|-------------|--------|------------------------|
| MUST NOT include raw credentials or environment values | R4 | resolved | verification: test |
| MUST NOT read or copy provider transcripts, Session history, or user prompts | R4 | resolved | verification: test |
| MUST NOT upload a support bundle or diagnostic result | R5 | resolved | verification: test and code review |
| MUST NOT mutate configuration, restart services, or fabricate health | R1/R2 | resolved | verification: test |
| MUST NOT make bot health a prerequisite for bundle generation | R3 | resolved | verification: test |

## Ambiguity Report

| Dimension | Score | Min | Status | Notes |
|-----------|-------|-----|--------|-------|
| Goal Clarity | 0.95 | 0.75 | ✓ | Output and time ceiling are explicit |
| Boundary Clarity | 0.98 | 0.70 | ✓ | Repair, upload, transcript access excluded |
| Constraint Clarity | 0.88 | 0.65 | ✓ | Time, size, platform, partial results locked |
| Acceptance Criteria | 0.90 | 0.70 | ✓ | Failure, privacy, export, installed smoke covered |
| **Ambiguity** | **0.08** | ≤0.20 | ✓ | Ready for planning |

## Interview Log

| Round | Perspective | Question summary | Decision locked |
|-------|-------------|------------------|-----------------|
| prior discussion | Researcher | What should one-click diagnostics collect? | Reuse runtime truth and bounded recent logs |
| prior discussion | Boundary Keeper | What must support bundles exclude? | Secrets, prompts, transcripts, upload, repair |
| auto | Failure Analyst | What if bot/check/export fails? | Partial report/bundle, explicit failure, no white screen |

---

*Phase: 20-one-click-diagnostics-and-support-bundle*
*Spec created: 2026-07-11*
