#!/bin/bash
# deploy/install.sh — 动态生成 plist 并安装到 ~/Library/LaunchAgents
#
# Usage:
#   ./deploy/install.sh              # 自动检测路径
#   PYTHON_BIN=/path/to/python ./deploy/install.sh  # 指定 python 路径

set -euo pipefail

# ── 路径推导 ──────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
HOME_DIR="$HOME"
LABEL="com.wxy.onlineworker"
PLIST_DEST="$HOME_DIR/Library/LaunchAgents/$LABEL.plist"

# Python 路径：优先用环境变量，否则自动检测 pyenv/system
if [[ -n "${PYTHON_BIN:-}" ]]; then
	PYTHON="$PYTHON_BIN"
elif command -v pyenv &>/dev/null; then
	PYTHON="$(pyenv which python3 2>/dev/null || which python3)"
else
	PYTHON="$(which python3)"
fi

# 验证 python 存在
if [[ ! -x "$PYTHON" ]]; then
	echo "ERROR: Python not found at $PYTHON" >&2
	exit 1
fi

PYTHON_DIR="$(dirname "$PYTHON")"

echo "Project dir : $PROJECT_DIR"
echo "Python      : $PYTHON"
echo "Plist dest  : $PLIST_DEST"

# ── 生成 plist ────────────────────────────────────────────────
cat >"$PLIST_DEST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>

    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON</string>
        <string>$PROJECT_DIR/main.py</string>
    </array>

    <key>WorkingDirectory</key>
    <string>$PROJECT_DIR</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>$PYTHON_DIR:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
        <key>HOME</key>
        <string>$HOME_DIR</string>
        <key>LANG</key>
        <string>en_US.UTF-8</string>
    </dict>

    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>

    <key>ThrottleInterval</key>
    <integer>10</integer>

    <key>StandardOutPath</key>
    <string>/tmp/onlineworker-launchd.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/onlineworker-launchd.log</string>

    <key>RunAtLoad</key>
    <true/>

    <key>ProcessType</key>
    <string>Interactive</string>
</dict>
</plist>
EOF

echo "Plist generated: $PLIST_DEST"

# ── 加载服务 ──────────────────────────────────────────────────
UID_NUM="$(id -u)"

# 先尝试卸载旧的（忽略错误）
launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null || true
sleep 1

# 加载新的
launchctl bootstrap "gui/$UID_NUM" "$PLIST_DEST"
echo "Service loaded: $LABEL"

# 启动
launchctl kickstart "gui/$UID_NUM/$LABEL"
echo "Service started."
echo ""
echo "Useful commands:"
echo "  Restart: launchctl kickstart -k gui/$UID_NUM/$LABEL"
echo "  Stop:    launchctl bootout gui/$UID_NUM/$LABEL"
echo "  Log:     tail -f /tmp/onlineworker.log"
