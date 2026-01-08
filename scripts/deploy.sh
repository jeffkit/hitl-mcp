#!/bin/bash
# ===========================================
# HIL-MCP DevCloud Service 快速部署脚本
# ===========================================

set -e

# 配置
SSH_HOST="devg"
REMOTE_DIR="~/projects/hil-mcp"
LOCAL_DIR="$(dirname "$0")"

echo "🚀 开始部署 DevCloud Service..."

# 1. 同步代码
echo "📦 同步代码到 $SSH_HOST..."
rsync -avz --delete \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.git' \
    --exclude 'data' \
    --exclude '.env' \
    --exclude 'mcp_server' \
    --exclude '*.log' \
    "$LOCAL_DIR/devcloud_service/" \
    "$SSH_HOST:$REMOTE_DIR/devcloud_service/"

# 2. 同步依赖文件（如果需要）
echo "📄 同步配置文件..."
rsync -avz \
    "$LOCAL_DIR/requirements.txt" \
    "$LOCAL_DIR/pyproject.toml" \
    "$SSH_HOST:$REMOTE_DIR/"

# 3. 重启服务
echo "🔄 重启服务..."
ssh "$SSH_HOST" << 'EOF'
cd ~/projects/hil-mcp

# 找到并杀掉旧进程
OLD_PID=$(pgrep -f "python.*devcloud_service.app" || true)
if [ -n "$OLD_PID" ]; then
    echo "停止旧进程: $OLD_PID"
    kill $OLD_PID 2>/dev/null || true
    sleep 2
fi

# 启动新进程（后台运行）
echo "启动新进程..."
nohup python -m devcloud_service.app >> devcloud_new.log 2>&1 &

# 等待服务启动
sleep 3

# 检查服务状态
NEW_PID=$(pgrep -f "python.*devcloud_service.app" || true)
if [ -n "$NEW_PID" ]; then
    echo "✅ 服务已启动，PID: $NEW_PID"
else
    echo "❌ 服务启动失败，请检查日志"
    tail -20 devcloud_new.log
    exit 1
fi

# 健康检查
sleep 2
if curl -s http://localhost:8080/health | grep -q healthy; then
    echo "✅ 健康检查通过"
else
    echo "⚠️ 健康检查失败，请检查日志"
fi
EOF

echo ""
echo "✅ 部署完成！"
echo ""
echo "查看日志: ssh $SSH_HOST 'tail -f $REMOTE_DIR/devcloud_new.log'"
