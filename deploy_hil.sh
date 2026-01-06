#!/bin/bash
# ===========================================
# HIL Server 部署脚本
# 部署到公网服务器（Relay 模式）或内网服务器（Direct 模式）
# ===========================================

set -e

# 配置
SSH_HOST="tcloud_hk"
REMOTE_DIR="~/projects/hil-mcp"
LOCAL_DIR="$(dirname "$0")"
HIL_PORT=8081

echo "🚀 开始部署 HIL Server 到 $SSH_HOST..."

# 1. 确保远程目录存在
echo "📁 创建远程目录..."
ssh "$SSH_HOST" "mkdir -p $REMOTE_DIR"

# 2. 同步 HIL Server 代码
echo "📦 同步 HIL Server 代码..."
rsync -avz --delete \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.git' \
    --exclude 'data' \
    --exclude '.env' \
    --exclude '*.log' \
    "$LOCAL_DIR/hil_server/" \
    "$SSH_HOST:$REMOTE_DIR/hil_server/"

# 3. 同步依赖文件
echo "📄 同步依赖文件..."
rsync -avz \
    "$LOCAL_DIR/requirements.txt" \
    "$SSH_HOST:$REMOTE_DIR/"

# 4. 安装依赖并重启服务
echo "🔄 安装依赖并重启服务..."
ssh "$SSH_HOST" << EOF
cd $REMOTE_DIR

# 创建虚拟环境（如果不存在）
if [ ! -d "venv" ]; then
    echo "创建虚拟环境..."
    python3 -m venv venv
fi

# 激活虚拟环境并安装依赖
source venv/bin/activate
pip install -r requirements.txt -q

# 找到并杀掉旧进程（兼容旧名称和新名称）
OLD_PID=\$(pgrep -f "python.*(relay_server|hil_server).app" || true)
if [ -n "\$OLD_PID" ]; then
    echo "停止旧进程: \$OLD_PID"
    kill \$OLD_PID 2>/dev/null || true
    sleep 2
fi

# 设置环境变量
export HIL_PORT=$HIL_PORT
export HIL_WORKER_TOKEN=""
export FORWARD_SERVICE_URL="http://9.135.76.10:8083"

# 启动新进程（后台运行，使用虚拟环境的 python）
echo "启动 HIL Server..."
nohup venv/bin/python -m hil_server.app >> hil.log 2>&1 &

# 等待服务启动
sleep 3

# 检查服务状态
NEW_PID=\$(pgrep -f "python.*hil_server.app" || true)
if [ -n "\$NEW_PID" ]; then
    echo "✅ 服务已启动，PID: \$NEW_PID"
else
    echo "❌ 服务启动失败，请检查日志"
    tail -20 hil.log
    exit 1
fi

# 健康检查
sleep 2
if curl -s http://localhost:$HIL_PORT/health | grep -q healthy; then
    echo "✅ 健康检查通过"
    curl -s http://localhost:$HIL_PORT/health | python3 -m json.tool 2>/dev/null || cat
else
    echo "⚠️ 健康检查失败，请检查日志"
    tail -10 hil.log
fi
EOF

echo ""
echo "✅ HIL Server 部署完成！"
echo ""
echo "服务地址: http://$SSH_HOST:$HIL_PORT"
echo "WebSocket: ws://$SSH_HOST:$HIL_PORT/ws"
echo ""
echo "查看日志: ssh $SSH_HOST 'tail -f $REMOTE_DIR/hil.log'"
