#!/usr/bin/env bash
# Install the latest locally built OnlineWorker DMG without rebuilding it.
#
# This is the fast path for "the DMG already exists; overwrite /Applications
# and restart". It is not a replacement for the full AGENTS packaged-app
# verification chain used for release confidence.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DMG_PATH="${1:-}"

if [ -z "$DMG_PATH" ]; then
	DMG_PATH="$(ls -t "$PROJECT_ROOT"/mac-app/src-tauri/target/release/bundle/dmg/*.dmg 2>/dev/null | head -n 1 || true)"
fi

if [ -z "$DMG_PATH" ] || [ ! -f "$DMG_PATH" ]; then
	echo "ERROR: DMG not found. Build first, or pass a DMG path."
	exit 1
fi

echo "=== Install Current OnlineWorker DMG ==="
echo "DMG: $DMG_PATH"
shasum -a 256 "$DMG_PATH"

if [ -d /Volumes/OnlineWorker ]; then
	echo "=== Detaching stale /Volumes/OnlineWorker ==="
	hdiutil detach /Volumes/OnlineWorker || hdiutil detach /Volumes/OnlineWorker -force || true
fi

echo "=== Mounting DMG ==="
hdiutil attach "$DMG_PATH" -nobrowse -noautoopen

cleanup() {
	if [ -d /Volumes/OnlineWorker ]; then
		hdiutil detach /Volumes/OnlineWorker >/dev/null 2>&1 || true
	fi
}
trap cleanup EXIT

APP_IN_DMG="/Volumes/OnlineWorker/OnlineWorker.app"
APP_IN_APPLICATIONS="/Applications/OnlineWorker.app"

if [ ! -d "$APP_IN_DMG" ]; then
	echo "ERROR: $APP_IN_DMG not found"
	exit 1
fi

echo "=== DMG app version ==="
plutil -p "$APP_IN_DMG/Contents/Info.plist" | sed -n '/CFBundleShortVersionString/p;/CFBundleVersion/p'

echo "=== DMG binary hashes ==="
shasum -a 256 "$APP_IN_DMG/Contents/MacOS/onlineworker-bot" "$APP_IN_DMG/Contents/MacOS/onlineworker-app"

echo "=== Stopping current OnlineWorker processes ==="
mapfile -t pids < <(ps -axo pid=,command= | awk '/OnlineWorker\.app\/Contents\/MacOS\/onlineworker-(app|bot)/ {print $1}')
if [ "${#pids[@]}" -gt 0 ]; then
	kill "${pids[@]}" || true
	sleep 1
fi
ps -axo pid,ppid,etime,command | rg "OnlineWorker.app|onlineworker-app|onlineworker-bot" || true

echo "=== Installing to /Applications ==="
rm -rf "$APP_IN_APPLICATIONS"
ditto "$APP_IN_DMG" "$APP_IN_APPLICATIONS"

echo "=== Installed binary hashes ==="
shasum -a 256 "$APP_IN_APPLICATIONS/Contents/MacOS/onlineworker-bot" "$APP_IN_APPLICATIONS/Contents/MacOS/onlineworker-app"

echo "=== Launching installed app ==="
open "$APP_IN_APPLICATIONS"
sleep 2

echo "=== Running processes ==="
ps -axo pid,ppid,etime,command | rg "OnlineWorker.app|onlineworker-app|onlineworker-bot" || true

echo "=== install-current-dmg complete ==="
