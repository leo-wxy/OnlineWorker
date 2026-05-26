#!/usr/bin/env bash
# Fast packaged-app iteration flow:
#   1. Build the DMG.
#   2. Install the freshly built DMG to /Applications.
#   3. Restart OnlineWorker and verify app/bot processes are running.
#
# Use this when the goal is "build, overwrite, restart, then let a human test".
# It intentionally avoids the full release verification chain.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STARTED_AT="$(date +%s)"

echo "=== Fast packaged verification ==="
echo "Project: $PROJECT_ROOT"
echo ""

echo "=== Step 1/2: Build DMG ==="
bash "$PROJECT_ROOT/scripts/build.sh"
echo ""

DMG_DIR="$PROJECT_ROOT/mac-app/src-tauri/target/release/bundle/dmg"
DMG_PATH="$(ls -t "$DMG_DIR"/*.dmg 2>/dev/null | head -n 1 || true)"

if [ -z "${DMG_PATH:-}" ] || [ ! -f "$DMG_PATH" ]; then
	echo "ERROR: build completed but no DMG was found"
	exit 1
fi

echo "=== Step 2/2: Install and restart ==="
bash "$PROJECT_ROOT/scripts/install-current-dmg.sh" "$DMG_PATH"
echo ""

FINISHED_AT="$(date +%s)"
ELAPSED=$((FINISHED_AT - STARTED_AT))
echo "=== Fast packaged verification complete (${ELAPSED}s) ==="
