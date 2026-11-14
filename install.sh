#!/bin/sh
# 检查通过后才安装到本机，并重启面板服务。用法：sh install.sh
set -e
cd "$(dirname "$0")"
sh tests/smoke.sh
TS=$(date +%Y%m%d-%H%M%S)
mkdir -p "$HOME/.agent-hub/backup"
cp "$HOME/.local/bin/hub" "$HOME/.agent-hub/backup/hub.$TS" 2>/dev/null || true
cp "$HOME/.agent-hub/ui.html" "$HOME/.agent-hub/backup/ui.$TS.html" 2>/dev/null || true
install -m 755 hub "$HOME/.local/bin/hub"
cp ui.html "$HOME/.agent-hub/ui.html"
cp README.md "$HOME/.agent-hub/README.md"
"$HOME/.local/bin/hub" ui --stop >/dev/null 2>&1 || true
sleep 1
"$HOME/.local/bin/hub" ui --no-window
echo "installed $TS"
