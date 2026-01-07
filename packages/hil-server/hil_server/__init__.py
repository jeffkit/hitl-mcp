"""
HIL Server (Human-in-the-Loop Server)

核心服务，支持两种运行模式：

1. Relay 模式（公网部署）：
   - 接收 MCP Server 的 HTTP 请求
   - 管理与 DevCloud Worker 的 WebSocket 连接
   - 转发消息请求到 Worker

2. Direct 模式（内网部署）：
   - 接收 MCP Server 的 HTTP 请求
   - 直接调用 fly-pigeon 发送消息
   - 接收飞鸽回调

通用功能：
   - 会话管理和回复存储
   - 回调解析和会话匹配
"""
