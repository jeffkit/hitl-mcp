#!/bin/bash
#
# 同步代码到 dev 服务器
#
# 使用方法:
#   ./sync_to_dev.sh [service]
#
# 参数:
#   service: forward, hil, all (默认 all)
#
# 示例:
#   ./sync_to_dev.sh forward  # 只同步 forward-service
#   ./sync_to_dev.sh hil      # 只同步 hil-server
#   ./sync_to_dev.sh          # 同步所有服务

set -e

# ============== 配置 ==============
DEV_HOST="dev"

# dev 服务器使用 monorepo 目录结构（与 devg 一致）
DEV_FORWARD_PATH="/root/projects/hil-mcp/packages/forward-service/forward_service"
DEV_HIL_PATH="/root/projects/hil-mcp/packages/hil-server/hil_server"

# 本地 monorepo 路径
LOCAL_FORWARD_PATH="$(dirname "$0")/../../packages/forward-service/forward_service"
LOCAL_HIL_PATH="$(dirname "$0")/../../packages/hil-server/hil_server"

# ============== 函数 ==============

sync_forward() {
    echo "📦 同步 Forward Service 到 dev..."
    
    # 同步主要代码文件
    rsync -avz --exclude '__pycache__' --exclude '*.pyc' \
        "$LOCAL_FORWARD_PATH/" "$DEV_HOST:$DEV_FORWARD_PATH/"
    
    # 清理缓存
    ssh "$DEV_HOST" "find $DEV_FORWARD_PATH -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true"
    
    # 重启服务
    echo "🔄 重启 hil-forward 服务..."
    ssh "$DEV_HOST" "sudo systemctl restart hil-forward"
    
    echo "✅ Forward Service 同步完成"
}

sync_hil() {
    echo "📦 同步 HIL Server 到 dev..."
    
    # 同步主要代码文件
    rsync -avz --exclude '__pycache__' --exclude '*.pyc' \
        "$LOCAL_HIL_PATH/" "$DEV_HOST:$DEV_HIL_PATH/"
    
    # 清理缓存
    ssh "$DEV_HOST" "find $DEV_HIL_PATH -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true"
    
    # 重启服务
    echo "🔄 重启 hil-server-direct 服务..."
    ssh "$DEV_HOST" "sudo systemctl restart hil-server-direct"
    
    echo "✅ HIL Server 同步完成"
}

# ============== 主逻辑 ==============

SERVICE="${1:-all}"

echo "================================"
echo "  同步代码到 dev 服务器"
echo "================================"
echo ""

case "$SERVICE" in
    forward)
        sync_forward
        ;;
    hil)
        sync_hil
        ;;
    all)
        sync_forward
        echo ""
        sync_hil
        ;;
    *)
        echo "❌ 未知服务: $SERVICE"
        echo "用法: $0 [forward|hil|all]"
        exit 1
        ;;
esac

echo ""
echo "🎉 同步完成!"
