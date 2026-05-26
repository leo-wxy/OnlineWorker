# OnlineWorker Repository Notes

This file gives coding agents and maintainers the minimum repository-specific
rules needed to work safely in this codebase.

## Scope

- Public repository surface only.
- Builtin providers in this repository: `codex`, `claude`.
- Additional provider packages may be mounted through the public extension
  boundary, but they are outside this repository.

## Core Rules

1. Validate packaged-app behavior against an installed `OnlineWorker.app`, not
   only source-mode runs.
2. If a change touches the Python bot sidecar, rebuild it before packaging.
3. Keep provider-specific behavior behind the current provider registry and
   runtime boundaries. Do not reintroduce hardcoded provider wiring into shared
   app surfaces.
4. Keep public docs and code free of non-public credentials, endpoints, or
   repository-external implementation details.
5. Never delete files outside this repository. User history, sessions, logs,
   databases, app data, credentials, and state under `~/.codex`, `~/.claude`,
   `~/Library`, `/Applications`, `~/.Trash`, or any other external location are
   not cleanup targets.
6. Do not implement cleanup scripts that physically delete session, history,
   log, database, or state files. Any cleanup must be reversible: first produce
   an explicit candidate list, then move approved files to a repository-local or
   user-approved quarantine/archive directory with a manifest, and provide a
   restore path.
7. Codex/Claude transcript files are user history. Do not classify a whole
   transcript as disposable because it contains smoke-test text, markers, tool
   output, or quoted evidence.
8. Any operation touching non-repository paths must be read-only unless the user
   explicitly asks for that exact write. A general request like "clean up smoke"
   is not permission to delete or move external files.

## Packaging

- Apple Silicon packaging entry point: `bash scripts/build.sh`
- Intel packaging is documented in [deploy/BUILD.md](deploy/BUILD.md)
- `scripts/build.sh` is the shared build pipeline
- `ONLINEWORKER_PLUGIN_SOURCE_DIRS` is the public build-time extension hook

## Runtime and Storage

- Installed app data lives under:
  - `~/Library/Application Support/OnlineWorker/config.yaml`
  - `~/Library/Application Support/OnlineWorker/.env`
- Source-mode bot state may also use repo-local files such as:
  - `config.yaml`
  - `.env`
  - `onlineworker_state.json`

## Validation

- Python tests live under `tests/`
- Rust/Tauri tests live under `mac-app/src-tauri`
- Frontend tests live under `mac-app/tests`
- For packaged-app changes, document whether installed-app verification was
  completed or remains unverified
- Daily packaged-app iteration should use the fast chain:
  `bash scripts/verify-packaged-fast.sh`.
- The fast chain means: build DMG, overwrite `/Applications/OnlineWorker.app`,
  restart the installed app, and verify `onlineworker-app` plus
  `onlineworker-bot` processes are running from `/Applications`.
- Use the complete packaged-app verification chain only for release/tag
  confidence, difficult runtime failures, suspected packaging corruption, or
  when the user explicitly asks for full verification.

## Git Commit

- Commit message format: `<type>(scope): <summary>`.
- `scope` is optional; use it when it clarifies the touched area, for example
  `notification`, `verify`, `docs`, `config`, or `ui`.
- `summary` must be Chinese, start with a verb, be 50 characters or less, and
  must not end with punctuation.
- Common `type` values: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`.
- Keep commits focused. Do not mix unrelated product changes, verification
  scripts, generated artifacts, and planning/documentation updates unless they
  are part of the same requested delivery.
- Before committing, run the smallest relevant verification for the touched
  files and include the exact commands/results in the handoff.
- Do not commit secrets, local app data, logs, installed app bundles, DMGs,
  or files from outside this repository.

Examples:

- `feat(notification): 接入插件化通知渠道`
- `fix(session): 清理图片发送后的输入状态`
- `docs(notification): 完善通知插件开发规范`
- `chore(verify): 增加快速验证安装脚本`

### Fast Packaged-App Iteration Chain

When the user says "开始验证", "打包验证", "重新验证", "打包 + 覆盖", or
similar wording during normal feature iteration, prefer the fast chain:

1. Run `bash scripts/verify-packaged-fast.sh`.
2. Confirm the command exits 0.
3. Report the generated DMG path, installed app path, and current
   `onlineworker-app` / `onlineworker-bot` PIDs.

This is enough when the purpose is to let the user immediately test the newly
installed app. Do not add hash, socket, log, or feature-smoke checks unless the
user asks for deeper verification or the fast chain fails.

### Complete Packaged-App Verification Chain

When the user says "开始验证", "打包验证", "重新验证", "打包 + 覆盖", or
similar wording for release/tag confidence, difficult runtime failures,
suspected packaging corruption, or explicit full verification, use the full
packaged-app verification chain:

Every step must have an action and an immediate verification before moving to
the next step. Do not merge "file copied" with "new app is running"; these are
separate facts with separate evidence.

1. Record the pre-existing runtime state.
   - Action: list current OnlineWorker-owned processes with a precise filter:
     `ps -axo pid,ppid,etime,command | rg "OnlineWorker.app|onlineworker-app|onlineworker-bot"`.
   - Verification: record old PIDs, elapsed time, and commands. If the command
     is blocked by permissions, request approval immediately and say that this
     process check is blocked.
2. Run source-level regression checks when code changed.
   - Action: run the smallest relevant Python/Rust test set before packaging.
   - Verification: record exact commands and pass/fail counts. If these fail,
     stop before building.
3. Build from the combined repository root entry point:
   `bash build.sh`.
   - Verification: the command exits 0 and reports the freshly generated DMG
     path.
4. Record the fresh artifact identity.
   - Action: hash the generated DMG with `shasum -a 256`.
   - Verification: report the DMG path and hash. This hash identifies the build
     being installed.
5. Mount the freshly generated DMG.
   - Action: detach any stale `/Volumes/OnlineWorker` mount first, then attach
     the new DMG. Prefer non-interactive attach options when appropriate, but
     do not skip content verification.
   - Verification: `/Volumes/OnlineWorker/OnlineWorker.app` exists and its
     `Info.plist` is readable.
6. Verify the DMG app contents before copying.
   - Action: read `/Volumes/OnlineWorker/OnlineWorker.app/Contents/Info.plist`
     and hash `/Volumes/OnlineWorker/OnlineWorker.app/Contents/MacOS/onlineworker-bot`.
   - Verification: version is the expected version, and the mounted sidecar
     hash is recorded.
7. Stop all old OnlineWorker-owned runtime processes.
   - Action: kill the old `onlineworker-app` and `onlineworker-bot` PIDs found
     in step 1. Include OnlineWorker-owned child runtime processes when their
     parent chain belongs to `onlineworker-bot`.
   - Verification: the kill command exits 0 or reports already-exited PIDs.
     Do not kill unrelated standalone Codex, Claude, terminal, editor, or
     system processes.
8. Verify old runtime processes are gone.
   - Action: run the same precise process filter again.
   - Verification: no OnlineWorker-owned business process remains. It is OK for
     the verification command's own `ps`/`rg` processes to appear; do not count
     those as OnlineWorker runtime processes.
9. Overwrite `/Applications/OnlineWorker.app`.
   - Action: remove the old installed app and copy the mounted app with
     `ditto /Volumes/OnlineWorker/OnlineWorker.app /Applications/OnlineWorker.app`.
   - Verification: both commands exit 0.
10. Verify installed app contents.
    - Action: compare hashes for
      `/Applications/OnlineWorker.app/Contents/MacOS/onlineworker-bot` and
      `/Volumes/OnlineWorker/OnlineWorker.app/Contents/MacOS/onlineworker-bot`,
      then read `/Applications/OnlineWorker.app/Contents/Info.plist`.
    - Verification: installed sidecar hash exactly equals mounted sidecar hash,
      and installed version matches the expected version.
11. Relaunch `/Applications/OnlineWorker.app`.
    - Action: run `open /Applications/OnlineWorker.app`.
    - Verification: this command alone only means launch was requested; it does
      not prove the new app is running.
12. Verify the relaunched runtime is new.
    - Action: run the precise process filter again and inspect each new PID
      with `ps -p <pid> -o pid=,etime=,comm=`.
    - Verification: new `onlineworker-app` and `onlineworker-bot` PIDs exist,
      their elapsed times are short relative to the relaunch, and their
      executable paths are under `/Applications/OnlineWorker.app`. If elapsed
      time shows an older process, stop and restart again.
13. Verify runtime IPC before feature smoke.
    - Action: check the relevant socket or health endpoint for the provider
      under test, for example the provider owner bridge socket in
      `~/Library/Application Support/OnlineWorker`.
    - Verification: the socket or health check responds from the newly started
      app.
14. Run the feature-specific smoke.
    - Action: run the smallest script or command that proves the target
      behavior, for example a Claude owner-bridge smoke that sends a unique
      marker and reads the assistant response back.
    - Verification: send succeeds, read succeeds, and the returned assistant
      content exactly matches the marker.
15. Check logs for errors from this run.
    - Action: inspect the relevant recent log file or system log after the
      smoke.
    - Verification: no traceback, bridge error, provider error, or permission
      routing error corresponds to the just-run smoke marker or timestamp.
16. Detach the DMG.
    - Action: `hdiutil detach /Volumes/OnlineWorker`.
    - Verification: detach exits 0, or any failure is reported with the exact
      reason.
17. Report only verified facts.
    - Action: summarize commands, hashes, PIDs, elapsed times, version, smoke
      marker, and log result.
    - Verification: do not claim packaged-app verification is complete unless
      all required steps above passed. Mark any skipped or failed step as
      unverified.

Do not claim packaged-app verification is complete after only building or only
overwriting. Do not claim relaunch is complete after only running `open`; a
valid relaunch requires evidence that old OnlineWorker processes were stopped
and new `onlineworker-app` / `onlineworker-bot` PIDs appeared afterward. If
relaunch or runtime verification fails, report that failure explicitly with the
command/output evidence.

Stopping and restarting are one indivisible verification action. Never leave the
installed app stopped as the end state of verification unless the user explicitly
asked to stop it. If a stop command succeeds, is interrupted, or partially
executes, immediately continue with the relaunch and post-start process/log
checks before reporting status.

Process verification output can be large and easy to misread. Prefer a precise
process filter over scanning truncated full-process output. If any command is
waiting for approval or permissions, say that immediately instead of silently
waiting or retrying with new command shapes.

## Reference Documents

- [README.md](README.md)
- [README.zh.md](README.zh.md)
- [CONTRIBUTING.md](CONTRIBUTING.md)
- [SUPPORT.md](SUPPORT.md)
- [deploy/BUILD.md](deploy/BUILD.md)
