#!/bin/bash
# ===========================================
# Forward Service DevCloud 部署脚本
# ===========================================

set -e

# 配置
SSH_HOST="devg"
REMOTE_DIR="~/projects/hil-mcp"
LOCAL_DIR="$(dirname "$0")"

# Forward Service 配置
FORWARD_PORT=8083
# Bot Key（从 Webhook URL 提取）
FORWARD_BOT_KEY="9dbe350e-3f53-4abe-8260-598c07e7bc21"
# 测试用目标 URL（httpbin 会返回请求内容）
FORWARD_URL="https://httpbin.org/post"

echo "🚀 开始部署 Forward Service 到 $SSH_HOST..."

# 1. 确保远程目录存在
echo "📁 创建远程目录..."
ssh "$SSH_HOST" "mkdir -p $REMOTE_DIR"

# 2. 同步 Forward Service 代码
echo "📦 同步 Forward Service 代码..."
rsync -avz --delete \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.git' \
    --exclude 'data' \
    --exclude '.env' \
    --exclude '*.log' \
    "$LOCAL_DIR/forward_service/" \
    "$SSH_HOST:$REMOTE_DIR/forward_service/"

# 3. 同步依赖文件（如果需要）
echo "📄 同步依赖文件..."
rsync -avz \
    "$LOCAL_DIR/requirements.txt" \
    "$SSH_HOST:$REMOTE_DIR/"

# 4. 安装依赖并重启服务
echo "🔄 安装依赖并重启服务..."
ssh "$SSH_HOST" << EOF
cd $REMOTE_DIR

# 安装/更新依赖
pip install -r requirements.txt -q 2>/dev/null || pip3 install -r requirements.txt -q
# 确保 httpx 已安装
pip install httpx -q 2>/dev/null || pip3 install httpx -q

# 找到并杀掉旧进程
OLD_PID=\$(pgrep -f "python.*forward_service.app" || true)
if [ -n "\$OLD_PID" ]; then
    echo "停止旧进程: \$OLD_PID"
    kill \$OLD_PID 2>/dev/null || true
    sleep 2
fi

# 设置环境变量
export FORWARD_BOT_KEY="$FORWARD_BOT_KEY"
export FORWARD_URL="$FORWARD_URL"
export FORWARD_PORT=$FORWARD_PORT
export FORWARD_TIMEOUT=30

# 启动新进程（后台运行）
echo "启动 Forward Service..."
echo "  FORWARD_PORT: \$FORWARD_PORT"
echo "  FORWARD_URL: \$FORWARD_URL"
nohup python -m forward_service.app >> forward.log 2>&1 &

# 等待服务启动
sleep 3

# 检查服务状态
NEW_PID=\$(pgrep -f "python.*forward_service.app" || true)
if [ -n "\$NEW_PID" ]; then
    echo "✅ 服务已启动，PID: \$NEW_PID"
else
    echo "❌ 服务启动失败，请检查日志"
    tail -20 forward.log
    exit 1
fi

# 健康检查
sleep 2
if curl -s http://localhost:$FORWARD_PORT/health | grep -q status; then
    echo "✅ 健康检查通过"
    curl -s http://localhost:$FORWARD_PORT/health | python3 -m json.tool 2>/dev/null || cat
else
    echo "⚠️ 健康检查可能失败，请检查日志"
    tail -10 forward.log
fi
EOF

echo ""
echo "✅ Forward Service 部署完成！"
echo ""
echo "============================================"
echo "📋 回调地址: http://<devcloud-ip>:$FORWARD_PORT/callback"
echo "❤️ 健康检查: http://<devcloud-ip>:$FORWARD_PORT/health"
echo "============================================"
echo ""
echo "请在飞鸽传书后台配置新机器人的回调地址"
echo ""
echo "查看日志: ssh $SSH_HOST 'tail -f $REMOTE_DIR/forward.log'"
