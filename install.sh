#!/bin/bash
# 家庭理财台账 · 本地版 一键安装（macOS）
# 用法：bash install.sh
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
echo "== 安装目录：$DIR =="

# 防呆：避免从系统目录误执行
case "$DIR" in
  /Applications/*|/Library/*) echo "拒绝在系统目录执行，请把项目放在工作空间"; exit 1 ;;
esac

# 1) Python 虚拟环境 + 依赖（绕过代理，避免公司代理导致 pypi 超时）
if [ ! -x "$DIR/.venv/bin/python" ]; then
  echo "== 创建虚拟环境 =="
  python3 -m venv "$DIR/.venv"
fi
echo "== 安装依赖 Flask / pywebview =="
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  "$DIR/.venv/bin/pip" install -q --timeout 60 --retries 3 -r "$DIR/requirements.txt"

mkdir -p "$DIR/data"

# 2) 由模板生成 launchd 配置（占位符 __APP_DIR__ 替换为实际路径）
AGENTS="$HOME/Library/LaunchAgents"
mkdir -p "$AGENTS"
for label in com.financeledger.web com.financeledger.nav; do
  sed "s|__APP_DIR__|$DIR|g" "$DIR/deploy/$label.plist" > "$AGENTS/$label.plist"
done

# 3) 加载定时任务（优先用现代 bootstrap 接口，失败则回退旧 load 接口）
echo "== 加载 launchd 任务 =="
UID_N=$(id -u)
for label in com.financeledger.web com.financeledger.nav; do
  launchctl bootout "gui/$UID_N/$label" 2>/dev/null || true
  if launchctl bootstrap "gui/$UID_N" "$AGENTS/$label.plist" 2>/dev/null; then
    echo "   $label 已加载 (bootstrap)"
  else
    launchctl unload "$AGENTS/$label.plist" 2>/dev/null || true
    launchctl load "$AGENTS/$label.plist" 2>/dev/null \
      && echo "   $label 已加载 (load 回退)" \
      || echo "   ⚠ $label 加载失败：请在【你自己的终端】手动执行 bash install.sh（AI 执行环境无法写 launchd）"
  fi
done

echo "== 安装完成 =="
echo "网页： http://127.0.0.1:8765"
echo "桌面： 双击 $DIR/dist/家庭理财台账.app"
echo "数据： $DIR/data/finance.db"
echo "每日 08:00 自动抓净值；开机自启网页服务"
echo "卸载： bash \"$DIR/uninstall.sh\""
