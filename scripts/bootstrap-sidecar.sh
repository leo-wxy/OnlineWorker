#!/bin/bash
# Create a local placeholder sidecar so fresh clones can run Tauri cargo tests
# before building the real PyInstaller bot binary.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if ! command -v rustc >/dev/null 2>&1; then
	echo "ERROR: rustc not found. Install Rust: https://rustup.rs" >&2
	exit 1
fi

TARGET_TRIPLE="$(rustc -vV | awk '/host:/{print $2}')"
if [ -z "$TARGET_TRIPLE" ]; then
	echo "ERROR: Could not detect target triple from rustc" >&2
	exit 1
fi

BIN_DIR="$PROJECT_ROOT/mac-app/src-tauri/binaries"
mkdir -p "$BIN_DIR"
for name in onlineworker-bot ccusage; do
	SIDECAR="$BIN_DIR/${name}-${TARGET_TRIPLE}"
	if [ -x "$SIDECAR" ]; then
		echo "Sidecar already exists: ${SIDECAR#$PROJECT_ROOT/}"
		continue
	fi
	cat >"$SIDECAR" <<EOF
#!/bin/sh
echo "$name sidecar is a local test placeholder." >&2
echo "Run scripts/build.sh to build the real PyInstaller sidecar before packaging or running the app service." >&2
exit 64
EOF
	chmod +x "$SIDECAR"
	echo "Created placeholder sidecar: ${SIDECAR#$PROJECT_ROOT/}"
done
