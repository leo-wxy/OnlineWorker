#!/usr/bin/env bash
# Restart the installed OnlineWorker.app as one verified operation.
set -euo pipefail

APP_PATH="${1:-/Applications/OnlineWorker.app}"

has_onlineworker_ancestor() {
	local pid="$PPID"
	local parent_pid command
	while [[ "$pid" =~ ^[0-9]+$ ]] && [ "$pid" -gt 1 ]; do
		read -r parent_pid command < <(ps -ww -o ppid=,command= -p "$pid" 2>/dev/null) || break
		case "$command" in
			*/onlineworker-bot*) return 0 ;;
		esac
		pid="$parent_pid"
	done
	return 1
}

if has_onlineworker_ancestor; then
	echo "ERROR: refusing to stop OnlineWorker from inside its own process tree."
	echo "Run this script from an external terminal or Codex Desktop task."
	exit 2
fi

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
	pids="$(runtime_pids || true)"
	if [ -n "$pids" ]; then
		echo "=== Force stopping remaining OnlineWorker processes ==="
		kill -KILL $pids || true
	fi
fi

if ! wait_for_no_runtime 3; then
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
