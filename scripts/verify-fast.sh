#!/usr/bin/env bash
# Fast local verification for common OnlineWorker changes.
#
# This intentionally does not build or install the packaged app. Use it before
# the full installed-app verification chain when iterating on code.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PIDS=()

run_step() {
	local name="$1"
	shift
	echo "=== $name ==="
	(
		cd "$PROJECT_ROOT"
		"$@"
	)
}

run_mac_step() {
	local name="$1"
	shift
	echo "=== $name ==="
	(
		cd "$PROJECT_ROOT/mac-app"
		"$@"
	)
}

run_tauri_step() {
	local name="$1"
	shift
	echo "=== $name ==="
	(
		cd "$PROJECT_ROOT/mac-app/src-tauri"
		"$@"
	)
}

run_step "Python tests" rtk pytest -q tests/test_events_streaming.py tests/test_notifications.py tests/test_config.py &
PIDS+=("$!")

run_step "Frontend tests" node --test mac-app/tests/appShell.test.mjs mac-app/tests/appTabs.test.mjs &
PIDS+=("$!")

run_tauri_step "Rust config tests" cargo test config_provider --lib &
PIDS+=("$!")

run_mac_step "Frontend build" npm run build &
PIDS+=("$!")

failed=0
for pid in "${PIDS[@]}"; do
	if ! wait "$pid"; then
		failed=1
	fi
done

if [ "$failed" -ne 0 ]; then
	echo "=== verify-fast failed ==="
	exit 1
fi

echo "=== verify-fast passed ==="
