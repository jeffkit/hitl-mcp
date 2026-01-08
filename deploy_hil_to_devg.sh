#!/bin/bash
# ===========================================
# HIL Server 部署到 devg 机器
# ===========================================

set -e

# 配置
SSH_HOST="devg"
REMOTE_DIR="~/projects/hil-mcp"
LOCAL_DIR="$(dirname "$0")/packages/hil-server"
HIL_PORT=8081

echo "🚀 开始部署 HIL Server 到 $SSH_HOST..."
echo "📁 本地目录: $LOCAL_DIR"
echo "📁 远程目录: $REMOTE_DIR"
echo ""

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
    --exclude '.venv' \
    --exclude 'uv.lock' \
    --exclude 'node_modules' \
    "$LOCAL_DIR/" \
    "$SSH_HOST:$REMOTE_DIR/"

# 3. 检查 pyproject.toml
echo "📄 检查 pyproject.toml..."
if [ -f "$LOCAL_DIR/pyproject.toml" ]; then
    rsync -avz "$LOCAL_DIR/pyproject.toml" "$SSH_HOST:$REMOTE_DIR/"
    echo "  ✅ pyproject.toml 已同步"
fi

# 4. 安装依赖并重启服务
echo "🔄 安装依赖并重启服务..."
ssh "$SSH_HOST" << 'EOF'
cd ~/projects/hil-mcp

# 检查是否安装了 uv
if ! command -v uv &> /dev/null; then
    echo "📦 安装 uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

# 同步依赖
echo "📦 同步 Python 依赖..."
uv sync --extra direct

# 找到并杀掉旧进程
OLD_PID=$(pgrep -f "python.*hil_server.app" || true)
if [ -n "$OLD_PID" ]; then
    echo "🛑 停止旧进程: $OLD_PID"
    kill $OLD_PID 2>/dev/null || true
    sleep 2
fi

# 设置环境变量
export HIL_PORT=8081
export HIL_MODE=direct  # Direct 模式
# export BOT_KEY="your_bot_key"  # 如果需要 Direct 模式,设置 BOT_KEY

# 启动新进程
echo "🚀 启动 HIL Server..."
nohup uv run python -m hil_server.app >> hil.log 2>&1 &

# 等待服务启动
sleep 3

# 检查服务状态
NEW_PID=$(pgrep -f "python.*hil_server.app" || true)
if [ -n "$NEW_PID" ]; then
    echo "✅ 服务已启动，PID: $NEW_PID"
else
    echo "❌ 服务启动失败，请检查日志"
    tail -30 hil.log
    exit 1
fi

# 健康检查
sleep 2
echo "🔍 健康检查..."
if curl -s http://localhost:8081/api/health | grep -q healthy; then
    echo "✅ 健康检查通过"
    curl -s http://localhost:8081/api/health | python3 -m json.tool 2>/dev/null || curl -s http://localhost:8081/api/health
else
    echo "⚠️ 健康检查失败，请检查日志"
    tail -10 hil.log
fi
EOF

echo ""
echo "✅ HIL Server 部署完成！"
echo ""
echo "📋 部署信息:"
echo "  主机: $SSH_HOST"
echo "  远程目录: $REMOTE_DIR"
echo "  服务端口: $HIL_PORT"
echo ""
echo "🔗 访问地址:"
echo "  HTTP: http://9.134.172.68:$HIL_PORT"
echo "  API: http://9.134.172.68:$HIL_PORT/api"
echo "  Health: http://9.134.172.68:$HIL_PORT/api/health"
echo ""
echo "📝 查看日志:"
echo "  ssh $SSH_HOST 'tail -f ~/projects/hil-mcp/hil.log'"
echo ""
echo "🔄 重启服务:"
echo "  ssh $SSH_HOST 'cd ~/projects/hil-mcp && pgrep -f \"hil_server.app\" | xargs kill && uv run python -m hil_server.app'"
