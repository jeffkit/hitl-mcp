#!/bin/bash
# ===========================================
# HIL-MCP DevCloud Worker 部署脚本
# 部署到 DevCloud（内网服务器）
# ===========================================

set -e

# 配置
SSH_HOST="devg"
REMOTE_DIR="~/projects/hil-mcp"
LOCAL_DIR="$(dirname "$0")"

# HIL Server 配置
# 注意：请根据实际部署情况修改以下配置
HIL_IP="101.32.48.45"   # HIL Server 的公网 IP 或域名
HIL_PORT=80             # 通过 nginx 反向代理
CALLBACK_PORT=8082

echo "🚀 开始部署 DevCloud Worker 到 $SSH_HOST..."

# 1. 确保远程目录存在
echo "📁 创建远程目录..."
ssh "$SSH_HOST" "mkdir -p $REMOTE_DIR"

# 2. 同步 DevCloud Worker 代码
echo "📦 同步 DevCloud Worker 代码..."
rsync -avz --delete \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.git' \
    --exclude 'data' \
    --exclude '.env' \
    --exclude '*.log' \
    "$LOCAL_DIR/devcloud_worker/" \
    "$SSH_HOST:$REMOTE_DIR/devcloud_worker/"

# 3. 同步依赖文件
echo "📄 同步依赖文件..."
rsync -avz \
    "$LOCAL_DIR/requirements.txt" \
    "$SSH_HOST:$REMOTE_DIR/"

# 4. 显示 HIL Server 地址
echo "📡 HIL Server 地址: $HIL_IP:$HIL_PORT"

# 5. 安装依赖并重启服务
echo "🔄 安装依赖并重启服务..."
ssh "$SSH_HOST" << EOF
cd $REMOTE_DIR

# 安装/更新依赖
pip install -r requirements.txt -q 2>/dev/null || pip3 install -r requirements.txt -q

# 找到并杀掉旧进程
OLD_PID=\$(pgrep -f "python.*devcloud_worker.worker" || true)
if [ -n "\$OLD_PID" ]; then
    echo "停止旧进程: \$OLD_PID"
    kill \$OLD_PID 2>/dev/null || true
    sleep 2
fi

# 从现有 .env 文件读取 BOT_KEY（如果存在）
if [ -f .env ]; then
    source .env 2>/dev/null || true
fi

# 设置环境变量
export HIL_URL="ws://$HIL_IP:$HIL_PORT/ws"
export HIL_TOKEN=""
export CALLBACK_PORT=$CALLBACK_PORT
# BOT_KEY 应该已经在 .env 中设置

if [ -z "\$BOT_KEY" ]; then
    echo "⚠️ 警告: BOT_KEY 未设置，请在 .env 文件中配置"
fi

# 启动新进程（后台运行）
echo "启动 DevCloud Worker..."
echo "  HIL_URL: \$HIL_URL"
echo "  CALLBACK_PORT: \$CALLBACK_PORT"
nohup python -m devcloud_worker.worker >> worker.log 2>&1 &

# 等待服务启动
sleep 3

# 检查服务状态
NEW_PID=\$(pgrep -f "python.*devcloud_worker.worker" || true)
if [ -n "\$NEW_PID" ]; then
    echo "✅ 服务已启动，PID: \$NEW_PID"
else
    echo "❌ 服务启动失败，请检查日志"
    tail -20 worker.log
    exit 1
fi

# 健康检查
sleep 2
if curl -s http://localhost:$CALLBACK_PORT/health | grep -q healthy; then
    echo "✅ 健康检查通过"
    curl -s http://localhost:$CALLBACK_PORT/health | python3 -m json.tool 2>/dev/null || cat
else
    echo "⚠️ 健康检查可能失败，请检查日志"
    tail -10 worker.log
fi
EOF

echo ""
echo "✅ DevCloud Worker 部署完成！"
echo ""
echo "回调地址: http://$SSH_HOST:$CALLBACK_PORT/callback"
echo "健康检查: http://$SSH_HOST:$CALLBACK_PORT/health"
echo ""
echo "查看日志: ssh $SSH_HOST 'tail -f $REMOTE_DIR/worker.log'"
echo ""
echo "⚠️ 请确保在飞鸽传书后台配置回调地址"
