"""HIL Server 内置引擎。

把原本由独立 Worker 进程维持的长连接（iLink 长轮询 / wecom-aibot WS）
收敛进 HIL Server 进程内，作为内置引擎直接运行：

- 收到上游用户消息 → 进程内直接调 storage.handle_callback（不走 WS）
- /api/send 命中内置引擎 → 进程内直接调 engine.send_message（不走 WS）
- /api/ilink/* → 直接调内置 ilink 引擎

外部 Worker（WS 注册，fly-pigeon 等）接口保留，作为回退/远程部署选项。
"""
from .base import BaseEngine
from .manager import engine_manager
from .ilink import ILinkEngine
from .wecom_aibot import WecomAibotEngine, WecomAibotStore

__all__ = ["BaseEngine", "engine_manager", "ILinkEngine", "WecomAibotEngine", "WecomAibotStore"]
