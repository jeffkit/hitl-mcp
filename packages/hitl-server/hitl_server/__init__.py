"""
HITL Server (Human-in-the-Loop Server)

本地单进程服务，内置 ilink + wecom-aibot 两个引擎：

- 维持长连接：进程内维持 iLink 长轮询 / 企微 AI Bot 的 WebSocket 连接
- 会话管理：给每条消息分配 [#short_id]，匹配「引用回复」，处理超时、多会话冲突
- HTTP API：供 MCP 端调用的 /api/send、/api/poll 等
- 管理台：扫码登录、填写企微凭证、查看引擎状态（/console）
"""
