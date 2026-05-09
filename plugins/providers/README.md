# Provider Plugins

Provider plugins describe AI coding backends through metadata and capability declarations. The manifest is the stable boundary consumed by config, UI, and verification.

## Layout

```text
plugins/providers/
  builtin/
    codex/plugin.yaml
    claude/plugin.yaml
```

## Public Defaults

Only providers under `builtin/` are public defaults. The current public default providers are:

- `codex`
- `claude`

External provider packages can be mounted through `ONLINEWORKER_PROVIDER_OVERLAY`. Keep this document focused on the public provider surface. Avoid adding local database paths, service health endpoints, or install commands here unless they are part of the public contract.
