#!/usr/bin/env bash
# 在 Linux 上把 PyInstaller 产物打成 .deb / .rpm（通过 fpm）。
#
# 前置：已在 Linux 上执行 packaging/build.sh 产出 dist/hitl-server/
# 依赖：fpm（gem install fpm 或 apt/dnf 装）
#
# 用法：
#   bash packaging/build.sh          # 先产出 dist/hitl-server/
#   bash packaging/build-linux-pkgs.sh 2.1.0
set -euo pipefail

PKG_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PKG_ROOT"

VERSION="${1:-2.1.0}"
BIN_DIR="$PKG_ROOT/dist/hitl-server"
STAGE="$PKG_ROOT/dist/stage"
SERVICE="$PKG_ROOT/packaging/hitl-server.service"

[ -d "$BIN_DIR" ] || { echo "❌ 找不到 $BIN_DIR，请先执行 packaging/build.sh"; exit 1; }
command -v fpm >/dev/null || { echo "❌ 缺少 fpm，请先安装：gem install fpm"; exit 1; }

# 暂存目录布局：/opt/hitl-server/* + /etc/systemd/system/hitl-server.service
rm -rf "$STAGE"
mkdir -p "$STAGE/opt/hitl-server" "$STAGE/etc/systemd/system"
cp -R "$BIN_DIR/." "$STAGE/opt/hitl-server/"
cp "$SERVICE" "$STAGE/etc/systemd/system/hitl-server.service"

mkdir -p "$PKG_ROOT/dist"

echo "==> 构建 .deb"
fpm -t deb -s dir -C "$STAGE" \
  --name hitl-server --version "$VERSION" --iteration 1 \
  --description "HITL Server (Human-in-the-Loop, iLink + WeCom AI)" \
  --url "https://github.com/jeffkit/hitl-mcp" \
  --license MIT \
  --depends systemd \
  --after-install <(printf 'systemctl daemon-reload || true\nsystemctl enable hitl-server || true\n') \
  --before-remove <(printf 'systemctl --no-reload disable hitl-server || true\nsystemctl stop hitl-server || true\n') \
  -p "$PKG_ROOT/dist/hitl-server_#{version}-#{iteration}_#{arch}.deb"

echo "==> 构建 .rpm"
fpm -t rpm -s dir -C "$STAGE" \
  --name hitl-server --version "$VERSION" --iteration 1 \
  --description "HITL Server (Human-in-the-Loop, iLink + WeCom AI)" \
  --url "https://github.com/jeffkit/hitl-mcp" \
  --license MIT \
  --depends systemd \
  --after-install <(printf 'systemctl daemon-reload || true\nsystemctl enable hitl-server || true\n') \
  --before-remove <(printf 'systemctl --no-reload disable hitl-server || true\nsystemctl stop hitl-server || true\n') \
  -p "$PKG_ROOT/dist/hitl-server-#{version}-#{iteration}.#{arch}.rpm"

rm -rf "$STAGE"
echo
echo "✅ Linux 包构建完成："
ls -la "$PKG_ROOT/dist"/hitl-server_*.deb "$PKG_ROOT/dist"/hitl-server-*.rpm 2>/dev/null
