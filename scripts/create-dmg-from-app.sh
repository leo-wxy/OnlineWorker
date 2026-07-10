#!/bin/bash
# Create a CI-safe DMG from an app bundle that Tauri already built successfully.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(tr -d '[:space:]' < "$PROJECT_ROOT/VERSION")"
APP_BUNDLE="${ONLINEWORKER_APP_BUNDLE_PATH:-$PROJECT_ROOT/mac-app/src-tauri/target/release/bundle/macos/OnlineWorker.app}"
DMG_OUTPUT_DIR="${ONLINEWORKER_DMG_OUTPUT_DIR:-$PROJECT_ROOT/mac-app/src-tauri/target/release/bundle/dmg}"
DITTO_BIN="${DITTO_BIN:-ditto}"
DISKUTIL_BIN="${DISKUTIL_BIN:-diskutil}"

case "${ONLINEWORKER_DMG_ARCH:-$(uname -m)}" in
	arm64 | aarch64)
		DMG_ARCH="aarch64"
		;;
	x86_64 | x64)
		DMG_ARCH="x64"
		;;
	*)
		echo "ERROR: unsupported DMG architecture" >&2
		exit 1
		;;
esac

if [ ! -x "$APP_BUNDLE/Contents/MacOS/onlineworker-app" ]; then
	echo "ERROR: built OnlineWorker app executable not found: $APP_BUNDLE" >&2
	exit 1
fi
if [ ! -x "$APP_BUNDLE/Contents/MacOS/onlineworker-bot" ]; then
	echo "ERROR: built OnlineWorker bot sidecar not found: $APP_BUNDLE" >&2
	exit 1
fi

STAGING_DIR="$(mktemp -d "${TMPDIR:-/tmp}/onlineworker-dmg.XXXXXX")"
cleanup() {
	rm -rf "$STAGING_DIR"
}
trap cleanup EXIT

"$DITTO_BIN" "$APP_BUNDLE" "$STAGING_DIR/OnlineWorker.app"
ln -s /Applications "$STAGING_DIR/Applications"

mkdir -p "$DMG_OUTPUT_DIR"
DMG_PATH="$DMG_OUTPUT_DIR/OnlineWorker_${VERSION}_${DMG_ARCH}.dmg"
rm -f "$DMG_PATH"

"$DISKUTIL_BIN" image create from \
	--format UDZO \
	--volumeName OnlineWorker \
	"$STAGING_DIR" \
	"$DMG_PATH"

if [ ! -f "$DMG_PATH" ]; then
	echo "ERROR: headless DMG was not created: $DMG_PATH" >&2
	exit 1
fi

echo "Headless fallback DMG: $DMG_PATH"
