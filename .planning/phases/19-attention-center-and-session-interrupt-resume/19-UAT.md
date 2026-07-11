---
status: complete
phase: 19-attention-center-and-session-interrupt-resume
source: [19-VERIFICATION.md]
started: 2026-07-11
updated: 2026-07-11
---

# Phase 19 UAT

## Tests

### 1. Installed Task Board B+A layout
expected: Existing Task Board Tab shows compact `需要你` / `正在运行` / `最近结束` groups and a selected right detail pane.
result: passed in installed `OnlineWorker.app`; desktop B+A hierarchy, selected detail, recent six-message excerpt, authority-safe controls, and no-white-screen relaunch were observed.

### 2. Installed narrow-width list/detail replacement
expected: Narrow width replaces the split view with list/detail navigation and Back.
result: waived at Phase 19 closeout by explicit user choice. Automated responsive contract passes, but the installed window was not visually exercised below the breakpoint, so this item is not represented as passed.

### 3. Real provider Session lifecycle
expected: Owned active turn exposes Interrupt; success appears only after provider abort/cancel evidence; user interruption moves to recent-ended with Continue; recovery reconnects/resumes the same Session without replay.
result: passed. Installed Codex interruption moved the same Session to recent-ended and Continue focused an empty composer. Installed Claude recovery returned `accepted=true` for Session `a824b4d4-469d-4f15-82a5-c18b480cd5de`; the next process used `--resume` with that exact id, `remapped=false`, and old/new markers each appeared once in the transcript.

### 4. Session load resilience and reversible test cleanup
expected: Rapid Session refresh cannot starve the owner bridge or white-screen the app; providers without source archive support use a reversible local archive overlay without deleting transcripts.
result: passed. Five rapid refresh clicks kept the page responsive, socket descriptors stable, owner bridge healthy, and logs advancing. Claude test Sessions `a824b4d4-469d-4f15-82a5-c18b480cd5de` and `e712b8a0-67e5-40ce-bcde-c4381a9e4ad0` disappeared from Active and appeared in Archived; source JSONL files were not deleted.

## Summary

total: 4
passed: 3
issues: 0
pending: 0
skipped: 1
blocked: 0

## Closeout Note

- Installed narrow-width visual behavior remains unverified and was explicitly waived for Phase 19 closeout. Source responsive coverage passes; no installed visual pass is claimed.
