#!/usr/bin/env bash
# 构建 HITL Server 自包含发布包（one-dir）。
#
# 本地（macOS / Linux）：
#   bash packaging/build.sh
# 产物：dist/hitl-server/  →  可直接 ./dist/hitl-server/hitl-server 运行
#
# CI：在 macOS 与 Ubuntu runner 上分别执行，产出对应平台压缩包。
set -euo pipefail

PKG_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PKG_ROOT"

CONSOLE_DIR="hitl_server/console"

# 1. 构建管理台 dist（若缺失或 --force）
if [ "${1:-}" = "--force" ] || [ ! -f "$CONSOLE_DIR/dist/index.html" ]; then
  echo "==> 构建管理台 dist"
  if [ -d "$CONSOLE_DIR/node_modules" ]; then
    ( cd "$CONSOLE_DIR" && pnpm run build )
  else
    ( cd "$CONSOLE_DIR" && pnpm install --frozen-lockfile && pnpm run build )
  fi
else
  echo "==> 管理台 dist 已存在，跳过（--force 可强制重建）"
fi

# 2. 确保打包环境（用现有 venv；安装 pyinstaller）
VENV_PY="$PKG_ROOT/.venv/bin/python"
if [ ! -x "$VENV_PY" ]; then
  echo "==> 建立 venv"
  uv venv
  uv sync
  VENV_PY="$PKG_ROOT/.venv/bin/python"
fi
echo "==> 安装 PyInstaller"
"$VENV_PY" -m pip install -q pyinstaller

# 3. PyInstaller
echo "==> PyInstaller 打包"
"$VENV_PY" -m PyInstaller packaging/hitl-server.spec \
  --distpath dist --workpath build --noconfirm

# 4. 产出压缩包（便于 release 上传）
BIN_DIR="dist/hitl-server"
OS_TAG="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH_TAG="$(uname -m)"
ARCHIVE="dist/hitl-server-${OS_TAG}-${ARCH_TAG}.tar.gz"
echo "==> 打包 $ARCHIVE"
tar -C dist -czf "$ARCHIVE" hitl-server

echo
echo "✅ 构建完成"
echo "   运行:  $BIN_DIR/hitl-server"
echo "   制品:  $ARCHIVE"
echo "   体积:  $(du -sh "$BIN_DIR" | cut -f1)"
