"""
回调处理器（简化版）

只负责接收飞鸽回调并转发给 Relay Server
不做任何会话管理或匹配逻辑
"""
import logging
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)


class CallbackHandler:
    """回调处理器（纯转发）"""
    
    def __init__(self):
        # 转发回调的函数
        self._forward_callback: Callable[[dict], Awaitable[None]] | None = None
    
    def set_forward_callback(
        self,
        callback: Callable[[dict], Awaitable[None]]
    ) -> None:
        """设置转发回调的函数"""
        self._forward_callback = callback
    
    async def handle_callback(self, data: dict) -> dict:
        """
        处理飞鸽回调（只转发，不处理）
        
        Args:
            data: 飞鸽回调原始数据
        
        Returns:
            响应数据
        """
        msg_type = data.get("msgtype", "")
        chat_id = data.get("chatid", "")
        
        # 忽略某些事件类型
        if msg_type in ("event", "enter_chat"):
            logger.info(f"忽略事件类型: {msg_type}")
            return {"errcode": 0, "errmsg": "ok"}
        
        logger.info(f"收到回调，转发给 Relay: chat_id={chat_id}, msg_type={msg_type}")
        
        # 转发给 Relay Server
        if self._forward_callback:
            try:
                await self._forward_callback(data)
                logger.info("回调已转发给 Relay")
            except Exception as e:
                logger.error(f"转发回调失败: {e}", exc_info=True)
        else:
            logger.warning("未设置转发回调函数，回调被丢弃")
        
        return {"errcode": 0, "errmsg": "ok"}


# 全局回调处理器
callback_handler = CallbackHandler()
