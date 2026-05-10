# Codebase Concerns

**Analysis Date:** 2026-05-10

## Tech Debt

**Cross-language runtime boundary (`Python + Rust + React + external CLIs`):**
- Issue: product behavior spans Python sidecar, Rust host, React UI, Telegram API, and provider CLIs
- Why: the product is intentionally a local AI workbench rather than a single-runtime app
- Impact: debugging and changes at integration seams are higher-cost than in a single-stack application
- Fix approach: keep contracts explicit, prefer narrow bridge surfaces, and preserve regression coverage at boundaries

**Provider abstraction still has provider-specific branches at host edges:**
- Issue: shared provider contracts exist, but some host/session logic still branches on runtime/provider identities
- Why: codex and claude capabilities are not fully symmetric yet
- Impact: adding a new provider or unifying behavior can surface hidden assumptions
- Fix approach: continue moving host-side behavior behind provider metadata/hooks where practical

## Known Bugs / Recent Failure Modes

**Tag-triggered workflow can run an old workflow revision if the tag points at an older commit:**
- Symptoms: rerunning a release/tag job still shows stale workflow steps
- Trigger: tag references a commit from before the latest workflow fixes
- Workaround: move/re-push the tag or use workflow_dispatch against the corrected revision
- Root cause: GitHub Actions evaluates the workflow file at the tagged commit

**Packaging/CI drift risk around Node/pnpm versions:**
- Symptoms: release build breaks during pnpm bootstrap
- Trigger: unpinned `pnpm@latest` advancing beyond Node 20 compatibility
- Workaround: pin compatible pnpm major for the build path
- Root cause: build tooling depends on external latest-channel behavior

## Security Considerations

**Local secret handling through `.env` and installed-app config:**
- Risk: Telegram tokens and optional provider API keys live in local env/config files
- Current mitigation: secrets are not committed; docs emphasize local env/config files and public repo cleanup
- Recommendations: keep generated docs free of secret values, preserve `.gitignore` boundaries, avoid copying raw env contents into planning artifacts

**Telegram control plane has real side effects:**
- Risk: bad allowlist/group configuration could expose local agent operations to the wrong Telegram context
- Current mitigation: `ALLOWED_USER_ID`, group/topic routing, setup connectivity checks
- Recommendations: preserve validation on setup surfaces and be cautious changing authorization-related handlers

## Performance Bottlenecks

**Session/event-heavy UI and runtime flows:**
- Problem: session polling, stream merging, and replay logic can become noisy and expensive as histories grow
- Evidence: the repo carries multiple dedicated tests around session polling, stream lifecycle, merge semantics, and reply watching
- Cause: product behavior depends on reconciling streamed/native/provider-specific event models
- Improvement path: keep polling/stream logic incremental and avoid whole-history recomputation when extending session UX

## Fragile Areas

**`main.py` bootstrap + handler registration:**
- Why fragile: single entry assembles logging, config, lock, lifecycle, Telegram app, and hook-bridge modes
- Common failures: startup behavior changes can affect packaging, source mode, or installed-app runtime differently
- Safe modification: prefer moving behavior into tested helpers/classes before expanding inline bootstrap logic
- Test coverage: covered, but still a high-blast-radius entrypoint

**`core/lifecycle.py` orchestration logic:**
- Why fragile: startup, reconnect, topic management, provider startup, and cleanup live here
- Common failures: regressions around autostart, reconnect, archived thread cleanup, or mixed provider state
- Safe modification: change in small steps with targeted lifecycle/runtime regression tests
- Test coverage: meaningful, but this remains one of the highest-risk shared modules

**Provider hook/registry boundary:**
- Why fragile: small schema/contract changes can cascade into builtin providers and app surfaces
- Common failures: descriptor mismatch, missing capability assumptions, provider visibility/managed state drift
- Safe modification: avoid casual contract expansion; update tests around `core/providers/*` and provider-specific adapters together

## Scaling Limits

**Single-machine local orchestration model:**
- Current capacity: built for an individual developer workstation and local CLI agent workflows
- Limit: not designed as a multi-tenant hosted service
- Symptoms at limit: more simultaneous provider/process/session coordination increases state/debug complexity rather than throughput capacity
- Scaling path: keep product expectations aligned with “local desktop workbench” rather than backend platform assumptions

## Dependencies at Risk

**GitHub-hosted packaging environment drift:**
- Risk: Node runtime deprecations and toolchain changes can break release automation without product code changes
- Impact: public release pipeline fails even when local app still builds
- Migration plan: pin compatible action majors and package-manager channels; periodically audit CI logs

**External CLI provider behavior:**
- Risk: `codex` / `claude` CLI output/session semantics may evolve outside the repo
- Impact: session parsing, approval flows, and runtime hooks can silently drift
- Migration plan: keep provider-specific tests broad enough to catch protocol/behavior changes early

## Missing Critical Features / Gaps

**Planning workspace absent before initialization:**
- Problem: GSD planning workflows cannot run until `.planning/` is initialized
- Current workaround: initialize planning artifacts explicitly (`gsd-new-project`, `gsd-map-codebase`)
- Blocks: roadmap/phase-driven planning workflows
- Implementation complexity: low, but process-sensitive

## Test Coverage Gaps

**Installed-app end-to-end verification is partially procedural, not fully automated in-repo:**
- What's not fully encoded: complete installed-app smoke validation after packaging
- Risk: source-mode and build-path tests may still miss app-bundle-only regressions
- Priority: High for release confidence
- Difficulty to test: requires packaged app execution and macOS-specific environment control

---

*Concerns audit: 2026-05-10*
*Update as issues are fixed or new ones discovered*
