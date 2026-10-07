#!/usr/bin/env bash
# Recover updater artifacts after a headless DMG fallback, using the same signer.
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUNDLE_ROOT="${1:?bundle root is required}"
APP="$BUNDLE_ROOT/macos/OnlineWorker.app"
ARCHIVE="$BUNDLE_ROOT/macos/OnlineWorker.app.tar.gz"
for binary in onlineworker-app onlineworker-bot ccusage; do
  test -x "$APP/Contents/MacOS/$binary"
done
COPYFILE_DISABLE=1 tar -czf "$ARCHIVE" -C "$BUNDLE_ROOT/macos" OnlineWorker.app
if [ -f "${TAURI_SIGNING_PRIVATE_KEY:-}" ]; then
  "$PROJECT_ROOT/mac-app/node_modules/.bin/tauri" signer sign --private-key-path "$TAURI_SIGNING_PRIVATE_KEY" "$ARCHIVE"
else
  "$PROJECT_ROOT/mac-app/node_modules/.bin/tauri" signer sign "$ARCHIVE"
fi
test -s "$ARCHIVE.sig"
