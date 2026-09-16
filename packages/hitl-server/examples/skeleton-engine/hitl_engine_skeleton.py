"""skeleton 渠道插件：外置 HITL Server 引擎的最小可运行示例。

安装本包后（pip install -e examples/skeleton-engine），entry point 组
``hitl_server.engines`` 会把 ``descriptor`` 注册进引擎注册表，
管理台 / MCP 即可通过 ``skeleton`` 渠道使用。

真实渠道请把 echo 逻辑替换为你的 IM 长连接 / Webhook 收发。
"""
from typing import Any, Awaitable, Callable, Dict, Optional

from hitl_server.engines.base import BaseEngine
from hitl_server.engines.registry import EngineContext, EngineDescriptor


class SkeletonEngine(BaseEngine):
    """最小引擎：把 /api/send 的消息原样当作用户回复回写会话。"""

    def __init__(self, bot_key: str = "skeleton-1", greet: str = "skeleton"):
        super().__init__(worker_type="skeleton", bot_key=bot_key)
        self._greet = greet
        self._running = False

    async def start(self) -> None:
        # 真实渠道：在这里建立长连接 / 启动后台轮询任务
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def send_message(self, payload: dict) -> dict:
        text = payload.get("message", "")
        # 真实渠道：把 text 发给你的 IM，收到用户回复后调用：
        #   await self.on_user_message(callback_data_dict)
        if self.on_user_message:
            await self.on_user_message({
                "message": f"[{self._greet}] {text}",
                "chat_id": payload.get("chat_id") or "skeleton-user",
            })
        return {"success": True, "chat_id": payload.get("chat_id") or "skeleton-user"}

    def status(self) -> dict:
        return {"worker_type": self.worker_type, "bot_key": self.bot_key, "running": self._running}


async def _build_startup(ctx: EngineContext) -> Optional[SkeletonEngine]:
    """启动时自动装配：env `SKELETON_ENABLED=true` 时启用。"""
    import os

    if os.getenv("SKELETON_ENABLED", "").lower() != "true":
        return None
    return SkeletonEngine(bot_key=os.getenv("SKELETON_BOT_KEY", "skeleton-1"))


async def _start(ctx: EngineContext, params: Dict[str, Any]) -> SkeletonEngine:
    """管理台 / 通用 API 动态启动。凭证字段见 descriptor.credentials。"""
    return SkeletonEngine(
        bot_key=params.get("bot_key") or "skeleton-1",
        greet=params.get("greet") or "skeleton",
    )


descriptor = EngineDescriptor(
    name="skeleton",
    title="Skeleton（示例插件）",
    build_startup=_build_startup,
    start=_start,
    credentials=["bot_key", "greet"],
)
