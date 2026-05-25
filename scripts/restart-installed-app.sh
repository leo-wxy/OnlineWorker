#!/usr/bin/env bash
# Restart the installed OnlineWorker.app as one verified operation.
set -euo pipefail

APP_PATH="${1:-/Applications/OnlineWorker.app}"

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

if [ ! -d "$APP_PATH" ]; then
	echo "ERROR: installed app not found: $APP_PATH"
	exit 1
fi

echo "=== Current OnlineWorker runtime ==="
runtime_lines || true

echo "=== Stopping OnlineWorker runtime ==="
pids="$(runtime_pids || true)"
if [ -n "$pids" ]; then
	kill $pids || true
fi

if ! wait_for_no_runtime 8; then
	echo "ERROR: OnlineWorker runtime did not stop cleanly"
	runtime_lines || true
	exit 1
fi

echo "=== Launching OnlineWorker ==="
open "$APP_PATH"

if ! wait_for_started 15; then
	echo "ERROR: OnlineWorker did not start with both app and bot processes"
	runtime_lines || true
	exit 1
fi

echo "=== Running OnlineWorker runtime ==="
runtime_lines

echo "=== restart-installed-app complete ==="
