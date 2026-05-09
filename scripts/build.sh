#!/bin/bash
# scripts/build.sh — Build OnlineWorker.app with embedded Python bot
# Usage: ./scripts/build.sh
#
# Pipeline:
#   1. PyInstaller: main.py → dist/onlineworker-bot (single binary)
#   2. Copy sidecar binary with target-triple suffix to mac-app/src-tauri/binaries/
#   3. Tauri build: produce .dmg in mac-app/src-tauri/target/release/bundle/dmg/
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

ensure_pnpm() {
	if command -v pnpm &>/dev/null; then
		return
	fi

	local nvm_dir="${NVM_DIR:-$HOME/.nvm}"
	if [ -s "${nvm_dir}/nvm.sh" ]; then
		# shellcheck disable=SC1090
		source "${nvm_dir}/nvm.sh"
		nvm use 20 >/dev/null
		hash -r
	fi

	if ! command -v pnpm &>/dev/null; then
		echo "ERROR: pnpm not found. Install Node.js 20 and pnpm, or load nvm before running scripts/build.sh"
		exit 1
	fi
}

# Detect target triple via rustc
if ! command -v rustc &>/dev/null; then
	echo "ERROR: rustc not found. Install Rust: https://rustup.rs"
	exit 1
fi
TARGET_TRIPLE=$(rustc -vV | awk '/host:/{print $2}')
if [ -z "$TARGET_TRIPLE" ]; then
	echo "ERROR: Could not detect target triple from rustc"
	exit 1
fi

echo "=== Build OnlineWorker ==="
echo "Project: $PROJECT_ROOT"
echo "Target:  $TARGET_TRIPLE"
echo "Profile: ${ONLINEWORKER_BUILD_PROFILE:-public}"
echo "Tauri config: ${TAURI_CONFIG_FILE:-src-tauri/tauri.conf.json}"
echo ""

# Step 1: Use arm64 Python for PyInstaller
PYTHON_ARM64="${PYTHON_ARM64:-$HOME/.pyenv/versions/3.13.1/bin/python3}"
if [ ! -f "$PYTHON_ARM64" ]; then
	echo "ERROR: arm64 Python not found at $PYTHON_ARM64"
	exit 1
fi
PYINSTALLER_CMD="$PYTHON_ARM64 -m PyInstaller"

# Step 2: Build Python bot binary
echo "=== Step 1/3: PyInstaller build ==="
cd "$PROJECT_ROOT"
$PYINSTALLER_CMD onlineworker.spec --clean --noconfirm
echo "Binary: $(ls -lh dist/onlineworker-bot)"
echo ""

# Step 3: Copy binary with target-triple suffix for Tauri sidecar
echo "=== Step 2/3: Copy sidecar binary ==="
mkdir -p "$PROJECT_ROOT/mac-app/src-tauri/binaries"
cp "$PROJECT_ROOT/dist/onlineworker-bot" \
	"$PROJECT_ROOT/mac-app/src-tauri/binaries/onlineworker-bot-${TARGET_TRIPLE}"
chmod +x "$PROJECT_ROOT/mac-app/src-tauri/binaries/onlineworker-bot-${TARGET_TRIPLE}"
echo "Sidecar: mac-app/src-tauri/binaries/onlineworker-bot-${TARGET_TRIPLE}"
echo ""

# Step 4: Build Tauri app (produces .dmg)
echo "=== Step 3/3: Tauri build ==="
ensure_pnpm
hash -r
cd "$PROJECT_ROOT/mac-app"
if [ ! -x "$PROJECT_ROOT/mac-app/node_modules/.bin/tauri" ]; then
	echo "=== Installing mac-app dependencies ==="
	pnpm install --no-frozen-lockfile
	echo ""
fi
pnpm tauri build --config "${TAURI_CONFIG_FILE:-src-tauri/tauri.conf.json}"

echo ""
echo "=== Build Complete ==="
DMG_PATH=$(ls "$PROJECT_ROOT/mac-app/src-tauri/target/release/bundle/dmg/"*.dmg 2>/dev/null || echo "")
if [ -n "$DMG_PATH" ]; then
	echo "DMG: $DMG_PATH"
else
	echo "DMG: check mac-app/src-tauri/target/release/bundle/dmg/"
fi
