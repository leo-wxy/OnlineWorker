# Support

## Scope

OnlineWorker currently targets:

- macOS
- public builtin providers: `codex`, `claude`

Private overlays are downstream integrations and are out of scope for public
support in this repository.

## Before Filing an Issue

Please include:

- macOS version
- OnlineWorker version or commit
- whether you ran from source or from an installed app
- which provider you used
- provider CLI version
- relevant logs or screenshots
- exact reproduction steps

## Validation Expectation

If the issue is about packaged app behavior, validate it against an installed
`OnlineWorker.app`. Source-mode results are useful for diagnosis, but they do
not replace packaged-app verification.

## Good Issue Reports

Good reports are:

- reproducible
- narrowly scoped
- clear about expected vs actual behavior
- attached to the smallest relevant logs
