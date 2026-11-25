#!/bin/bash
# 家庭理财台账 · 本地版 环境安装（macOS）
# 手动模式：不配置开机自启与定时任务；服务随桌面 App 启动、随关闭退出。
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

# 2) 手动模式：不生成、不加载任何 launchd 任务。
#    若历史上装过旧版常驻任务，这里主动卸载，避免与"随开随关"冲突。
AGENTS="$HOME/Library/LaunchAgents"
UID_N=$(id -u)
for label in com.financeledger.web com.financeledger.nav com.financeledger.backup; do
  launchctl bootout "gui/$UID_N/$label" 2>/dev/null || true
  launchctl unload "$AGENTS/$label.plist" 2>/dev/null || true
  rm -f "$AGENTS/$label.plist"
done
echo "== 已确保没有常驻/开机自启任务 =="

echo "== 安装完成 =="
echo "启动： 双击 $DIR/dist/家庭理财台账.app（打开时自动同步净值+备份）"
echo "退出： 关闭窗口即彻底退出并释放监听端口"
echo "网页： http://127.0.0.1:31415（仅在 App 开着时可访问）"
echo "数据： $DIR/data/finance.db"
echo "备份： $DIR/data/backups/ （每次启动 App 备份一次，保留最近 30 份）"
echo "卸载： bash \"$DIR/uninstall.sh\""
