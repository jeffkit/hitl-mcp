"""
DevCloud Worker

运行在 DevCloud（内网）的 Worker，负责：
1. 连接到 Relay Server（WebSocket）
2. 接收消息发送请求
3. 调用 fly-pigeon 发送消息
4. 接收企微回调并推送给 Relay
"""
