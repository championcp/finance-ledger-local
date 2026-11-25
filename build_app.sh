#!/bin/bash
# 家庭理财台账 · 构建桌面运行程序（macOS .app 启动器）
#
# 说明：本 App 是「启动器」而非打包体——双击后用项目虚拟环境运行 desktop.py，
# 源码即改即生效，无需每次重新构建。构建脚本用于从零生成/修复 .app 结构，
# 便于换机器或误删后复现。产物在 dist/，不进 git（.gitignore 已排除）。
#
# 用法：bash build_app.sh
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
APP="$DIR/dist/家庭理财台账.app"
CONTENTS="$APP/Contents"
MACOS="$CONTENTS/MacOS"
VERSION="${APP_VERSION:-1.2}"

echo "== 构建家庭理财台账.app（版本 $VERSION）=="
echo "   项目目录：$DIR"

# 1) 依赖检查（没有虚拟环境就提示先 install.sh）
if [ ! -x "$DIR/.venv/bin/python" ]; then
  echo "!! 未检测到 .venv，请先运行 bash install.sh" >&2
  exit 1
fi
if ! "$DIR/.venv/bin/python" -c 'import flask, webview, openpyxl, Crypto' 2>/dev/null; then
  echo "!! 依赖不全，请先运行 bash install.sh" >&2
  exit 1
fi

# 2) 清理旧结构后重建（保留 dist 下其他内容）
rm -rf "$APP"
mkdir -p "$MACOS"

# 3) 启动器：路径相对推导，不硬编码用户名，便于公开仓库复现
cat > "$MACOS/launcher" <<'LAUNCHER'
#!/bin/bash
# 家庭理财台账 · 桌面启动器
# 路径相对于 .app 所在目录推导，不硬编码用户名，便于公开仓库复现。
APP_DIR="$(cd "$(dirname "$0")/../../../.." && pwd)"
PY="$APP_DIR/.venv/bin/python"
if [ ! -x "$PY" ]; then
  osascript -e 'display alert "家庭理财台账" message "尚未安装依赖，请先运行 install.sh"'
  exit 1
fi
cd "$APP_DIR" || exit 1
exec "$PY" "$APP_DIR/desktop.py"
LAUNCHER
chmod +x "$MACOS/launcher"

# 4) Info.plist：写入版本号
cat > "$CONTENTS/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>家庭理财台账</string>
  <key>CFBundleDisplayName</key><string>家庭理财台账</string>
  <key>CFBundleIdentifier</key><string>local.financeledger.desktop</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleExecutable</key><string>launcher</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST

# 5) 刷新 Finder 图标缓存
touch "$APP"
echo "== 构建完成：$APP"
echo "   双击即可启动；关闭窗口会彻底退出并释放端口。"
