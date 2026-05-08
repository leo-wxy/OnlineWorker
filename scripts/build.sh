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
cd "$PROJECT_ROOT/mac-app"
pnpm tauri build

echo ""
echo "=== Build Complete ==="
DMG_PATH=$(ls "$PROJECT_ROOT/mac-app/src-tauri/target/release/bundle/dmg/"*.dmg 2>/dev/null || echo "")
if [ -n "$DMG_PATH" ]; then
	echo "DMG: $DMG_PATH"
else
	echo "DMG: check mac-app/src-tauri/target/release/bundle/dmg/"
fi
