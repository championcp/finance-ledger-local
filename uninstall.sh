#!/bin/bash
# 卸载定时与开机自启（不删除数据）
set -e
AGENTS="$HOME/Library/LaunchAgents"
UID_N=$(id -u)
for label in com.financeledger.web com.financeledger.nav; do
  launchctl bootout "gui/$UID_N/$label" 2>/dev/null || true
  launchctl unload "$AGENTS/$label.plist" 2>/dev/null || true
  rm -f "$AGENTS/$label.plist"
done
echo "已卸载定时任务与开机自启。数据文件与桌面应用未删除。"
