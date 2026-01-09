#!/bin/bash
#
# 同步代码到 devg 服务器
#
# 使用方法:
#   ./sync_to_devg.sh [service]
#
# 参数:
#   service: forward, hil, all (默认 all)
#
# 示例:
#   ./sync_to_devg.sh forward  # 只同步 forward-service
#   ./sync_to_devg.sh hil      # 只同步 hil-server
#   ./sync_to_devg.sh          # 同步所有服务

set -e

# ============== 配置 ==============
DEVG_HOST="devg"

# devg 服务器使用新的 monorepo 目录结构
DEVG_FORWARD_PATH="/data/projects/hil-mcp/packages/forward-service/forward_service"
DEVG_HIL_PATH="/data/projects/hil-mcp/packages/hil-server/hil_server"

# 本地 monorepo 路径
LOCAL_FORWARD_PATH="$(dirname "$0")/../../packages/forward-service/forward_service"
LOCAL_HIL_PATH="$(dirname "$0")/../../packages/hil-server/hil_server"

# ============== 函数 ==============

sync_forward() {
    echo "📦 同步 Forward Service 到 devg..."
    
    # 同步主要代码文件
    rsync -avz --exclude '__pycache__' --exclude '*.pyc' \
        "$LOCAL_FORWARD_PATH/" "$DEVG_HOST:$DEVG_FORWARD_PATH/"
    
    # 清理缓存
    ssh "$DEVG_HOST" "find $DEVG_FORWARD_PATH -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true"
    
    # 重启服务
    echo "🔄 重启 hil-forward 服务..."
    ssh "$DEVG_HOST" "sudo systemctl restart hil-forward"
    
    echo "✅ Forward Service 同步完成"
}

sync_hil() {
    echo "📦 同步 HIL Server 到 devg..."
    
    # 同步主要代码文件
    rsync -avz --exclude '__pycache__' --exclude '*.pyc' \
        "$LOCAL_HIL_PATH/" "$DEVG_HOST:$DEVG_HIL_PATH/"
    
    # 清理缓存
    ssh "$DEVG_HOST" "find $DEVG_HIL_PATH -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true"
    
    # 检查服务是否存在
    if ssh "$DEVG_HOST" "systemctl list-units --type=service | grep -q hil-server"; then
        echo "🔄 重启 hil-server 服务..."
        ssh "$DEVG_HOST" "sudo systemctl restart hil-server"
    else
        echo "⚠️ hil-server 服务未配置，跳过重启"
    fi
    
    echo "✅ HIL Server 同步完成"
}

# ============== 主逻辑 ==============

SERVICE="${1:-all}"

echo "================================"
echo "  同步代码到 devg 服务器"
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
