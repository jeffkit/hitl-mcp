#!/bin/bash
#
# Forward Service 部署脚本
#
# 使用方法:
#   1. 修改下方配置
#   2. chmod +x deploy_forward.sh
#   3. ./deploy_forward.sh
#

set -e

# ============== 配置区域 ==============
# 请根据实际情况修改以下配置

# 企微机器人 Webhook Key（必填）
export FORWARD_BOT_KEY="your-bot-key"

# 默认转发目标 URL（必填）
export FORWARD_URL="https://your-api.com/handle"

# 服务端口
export FORWARD_PORT=8083

# 转发请求超时时间（秒）
export FORWARD_TIMEOUT=30

# 高级配置：多目标 URL 映射（JSON 格式，可选）
# export FORWARD_RULES='{"chat_id_1": "https://api1.com", "chat_id_2": "https://api2.com"}'

# ============== 部署逻辑 ==============

echo "================================"
echo "  Forward Service 部署脚本"
echo "================================"
echo ""

# 检查配置
if [ "$FORWARD_BOT_KEY" == "your-bot-key" ]; then
    echo "❌ 请先配置 FORWARD_BOT_KEY"
    exit 1
fi

if [ "$FORWARD_URL" == "https://your-api.com/handle" ]; then
    echo "❌ 请先配置 FORWARD_URL"
    exit 1
fi

echo "配置信息:"
echo "  - BOT_KEY: ${FORWARD_BOT_KEY:0:10}..."
echo "  - FORWARD_URL: $FORWARD_URL"
echo "  - PORT: $FORWARD_PORT"
echo ""

# 检查是否已有进程运行
if pgrep -f "forward_service.app" > /dev/null; then
    echo "检测到 Forward Service 正在运行，停止旧进程..."
    pkill -f "forward_service.app" || true
    sleep 2
fi

# 启动服务
echo "启动 Forward Service..."
nohup python -m forward_service.app >> forward.log 2>&1 &

sleep 2

# 验证启动
if pgrep -f "forward_service.app" > /dev/null; then
    echo ""
    echo "✅ Forward Service 启动成功!"
    echo ""
    echo "健康检查: curl http://localhost:$FORWARD_PORT/health"
    echo "查看日志: tail -f forward.log"
    echo ""
    echo "请在飞鸽传书后台配置回调地址:"
    echo "  http://your-server:$FORWARD_PORT/callback"
else
    echo ""
    echo "❌ Forward Service 启动失败，请查看日志:"
    echo "  tail -f forward.log"
    exit 1
fi
