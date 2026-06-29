"""内置引擎抽象基类。

每种上游渠道（ilink / wecom-aibot）实现一个 Engine，在 HIL Server 进程内
维持单例长连接。Engine 收到用户消息后，通过 on_user_message 回调把消息
转成 fly-pigeon 兼容结构交给 storage.handle_callback；发送时由 /api/send
进程内调用 engine.send_message。
"""
from abc import ABC, abstractmethod
from typing import Awaitable, Callable, Optional


class BaseEngine(ABC):
    """内置引擎基类。"""

    def __init__(self, worker_type: str, bot_key: str):
        self.worker_type = worker_type
        self.bot_key = bot_key
        # 收到用户消息时触发：参数为 fly-pigeon 兼容 callback_data dict
        self.on_user_message: Optional[Callable[[dict], Awaitable[None]]] = None

    @abstractmethod
    async def start(self) -> None:
        """启动引擎（建立长连接、启动后台轮询等）。"""

    @abstractmethod
    async def stop(self) -> None:
        """停止引擎（清理连接、取消后台任务等）。"""

    @abstractmethod
    async def send_message(self, payload: dict) -> dict:
        """处理 /api/send 下行的 send_message 请求。

        Args:
            payload: 与 WS worker 协议一致的 send_message payload，含
                short_id / message / chat_id / project_name / wait_reply 等。

        Returns:
            {"success": bool, "chat_id"?: str, "error"?: str}
            回传实际使用的 chat_id（收件人 openid），供 HIL Server 关联 session。
        """

    @abstractmethod
    def status(self) -> dict:
        """返回引擎当前状态（供管理台展示）。

        至少包含 worker_type / bot_key / running；各引擎可补充渠道特有字段
        （如 ilink 的 logged_in / activated_users，wecom-aibot 的 connected / bot_id）。
        """
