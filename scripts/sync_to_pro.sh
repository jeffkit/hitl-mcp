#!/bin/bash
#
# 同步代码到 Pro 服务器
#
# 使用方法:
#   ./sync_to_pro.sh [service]
#
# 参数:
#   service: forward, hil, all (默认 all)
#
# 示例:
#   ./sync_to_pro.sh forward  # 只同步 forward-service
#   ./sync_to_pro.sh hil      # 只同步 hil-server
#   ./sync_to_pro.sh          # 同步所有服务

set -e

# ============== 配置 ==============
PRO_HOST="pro"

# Pro 服务器目录结构
PRO_FORWARD_PATH="/data/projects/hitl/packages/forward-service/forward_service"
PRO_HIL_PATH="/data/projects/hitl/packages/hil-server/hil_server"

# 本地 monorepo 路径
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOCAL_FORWARD_PATH="$SCRIPT_DIR/../packages/forward-service/forward_service"
LOCAL_HIL_PATH="$SCRIPT_DIR/../packages/hil-server/hil_server"

# ============== 函数 ==============

sync_forward() {
    echo "📦 同步 Forward Service 到 Pro..."
    
    # 同步主要代码文件
    rsync -avz --exclude '__pycache__' --exclude '*.pyc' \
        "$LOCAL_FORWARD_PATH/" "$PRO_HOST:$PRO_FORWARD_PATH/"
    
    # 清理缓存
    ssh "$PRO_HOST" "find $PRO_FORWARD_PATH -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true"
    
    # 重启服务
    echo "🔄 重启 forward-service 服务..."
    ssh "$PRO_HOST" "sudo systemctl restart forward-service"
    
    echo "✅ Forward Service 同步完成"
}

sync_hil() {
    echo "📦 同步 HIL Server 到 Pro..."
    
    # 同步主要代码文件
    rsync -avz --exclude '__pycache__' --exclude '*.pyc' \
        "$LOCAL_HIL_PATH/" "$PRO_HOST:$PRO_HIL_PATH/"
    
    # 清理缓存
    ssh "$PRO_HOST" "find $PRO_HIL_PATH -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true"
    
    # 重启服务
    echo "🔄 重启 hil-service 服务..."
    ssh "$PRO_HOST" "sudo systemctl restart hil-service"
    
    echo "✅ HIL Server 同步完成"
}

# ============== 主逻辑 ==============

SERVICE="${1:-all}"

echo "================================"
echo "  同步代码到 Pro 服务器"
echo "  (21.6.243.90 - hitl.woa.com)"
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
echo ""
echo "查看服务状态:"
echo "  ssh pro 'sudo systemctl status hil-service forward-service'"
