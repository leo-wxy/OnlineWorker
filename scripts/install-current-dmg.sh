#!/usr/bin/env bash
# Install the latest locally built OnlineWorker DMG without rebuilding it.
#
# This is the fast path for "the DMG already exists; overwrite /Applications
# and restart". It is not a replacement for the full AGENTS packaged-app
# verification chain used for release confidence.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DMG_PATH="${1:-}"

runtime_lines() {
	ps -axo pid=,ppid=,etime=,command= | awk '
		$4 ~ /^\/Applications\/OnlineWorker\.app\/Contents\/MacOS\/onlineworker-(app|bot)$/ {
			print
		}
	'
}

runtime_pids() {
	runtime_lines | awk '{print $1}'
}

wait_for_no_runtime() {
	local deadline=$((SECONDS + ${1:-8}))
	while [ "$SECONDS" -lt "$deadline" ]; do
		if [ -z "$(runtime_pids)" ]; then
			return 0
		fi
		sleep 0.5
	done
	return 1
}

wait_for_started() {
	local deadline=$((SECONDS + ${1:-15}))
	while [ "$SECONDS" -lt "$deadline" ]; do
		if runtime_lines | awk '
			$4 ~ /\/onlineworker-app$/ { app += 1 }
			$4 ~ /\/onlineworker-bot$/ { bot += 1 }
			END { exit !(app >= 1 && bot >= 1) }
		'; then
			return 0
		fi
		sleep 0.5
	done
	return 1
}

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
shasum -a 256 "$APP_IN_DMG/Contents/MacOS/onlineworker-bot" "$APP_IN_DMG/Contents/MacOS/onlineworker-app" "$APP_IN_DMG/Contents/MacOS/ccusage"

echo "=== Stopping current OnlineWorker processes ==="
pids="$(runtime_pids || true)"
if [ -n "$pids" ]; then
	kill $pids || true
fi

if ! wait_for_no_runtime 8; then
	echo "ERROR: OnlineWorker runtime did not stop cleanly"
	runtime_lines || true
	exit 1
fi
runtime_lines || true

echo "=== Installing to /Applications ==="
rm -rf "$APP_IN_APPLICATIONS"
ditto "$APP_IN_DMG" "$APP_IN_APPLICATIONS"

echo "=== Installed binary hashes ==="
shasum -a 256 "$APP_IN_APPLICATIONS/Contents/MacOS/onlineworker-bot" "$APP_IN_APPLICATIONS/Contents/MacOS/onlineworker-app" "$APP_IN_APPLICATIONS/Contents/MacOS/ccusage"

echo "=== Launching installed app ==="
open "$APP_IN_APPLICATIONS"

if ! wait_for_started 15; then
	echo "ERROR: OnlineWorker did not start with both app and bot processes"
	runtime_lines || true
	exit 1
fi

echo "=== Running processes ==="
runtime_lines

echo "=== install-current-dmg complete ==="
