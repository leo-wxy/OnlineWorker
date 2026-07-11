---
status: complete
phase: 20-one-click-diagnostics-and-support-bundle
source: [20-VERIFICATION.md]
started: 2026-07-11
updated: 2026-07-11
---

# Phase 20 UAT

## Tests

### 1. Installed diagnostics result
expected: Settings > Maintenance runs diagnostics without a healthy bot dependency, shows independent pass/warning/failure groups, and preserves partial results when a check is unavailable.
result: passed. Installed Settings > Maintenance returned nine independent healthy checks for version 1.8.0, managed service, configuration, two provider plugins, owner bridge, provider baseline, recent log, Codex, and Claude. Source coverage separately verifies partial results for stopped/invalid inputs.

### 2. Save cancellation
expected: Canceling the native support-bundle save dialog creates no ZIP and leaves app/runtime state unchanged.
result: passed. Finder save panel is brought to the foreground through a visible Finder host. Chinese cancellation error `-128` is treated as cancellation, the UI leaves busy state without an error, and the canceled target file was absent.

### 3. Support ZIP privacy boundary
expected: Exported ZIP contains only the documented generated files; it excludes raw `.env`, raw `config.yaml`, credentials, tokens, Session prompts/conversations, provider transcripts/history, and caps the recent log excerpt at 2 MiB.
result: passed. Final ZIP contains only `diagnostic-summary.json`, `provider-inventory.json`, `config-sanitized.yaml`, `logs/onlineworker-recent.log`, `manifest.json`, and `diagnostic-report.txt`. No `__MACOSX`, raw config/env, transcript/history, HOME path, or known token pattern was present. The log was below 2 MiB, and comparison against every installed `.env` value of length at least four returned `0` matches.

### 4. Finder reveal
expected: After successful export, Reveal opens Finder with the generated local ZIP selected.
result: passed. Finder opened `/private/tmp`, selected `OnlineWorker-phase20-UAT-private-final.zip`, and displayed its generated contents in the preview pane.

## Summary

total: 4
passed: 4
issues: 0
pending: 0
skipped: 0
blocked: 0
