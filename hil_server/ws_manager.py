"""
WebSocket 连接管理器

管理与 DevCloud Worker 的 WebSocket 连接
"""
import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Any

from fastapi import WebSocket

from .config import config
from .storage import storage

logger = logging.getLogger(__name__)


@dataclass
class WorkerConnection:
    """Worker 连接信息"""
    worker_id: str
    websocket: WebSocket
    connected_at: datetime = field(default_factory=datetime.now)
    last_heartbeat: datetime = field(default_factory=datetime.now)
    is_alive: bool = True


class WebSocketManager:
    """WebSocket 连接管理器"""
    
    def __init__(self):
        # 已连接的 Workers (worker_id -> WorkerConnection)
        self._workers: dict[str, WorkerConnection] = {}
        self._lock = asyncio.Lock()
        # 回调处理器
        self._callback_handlers: dict[str, Callable] = {}
    
    @property
    def has_worker(self) -> bool:
        """是否有可用的 Worker"""
        return len(self._workers) > 0
    
    async def register_worker(
        self,
        worker_id: str,
        websocket: WebSocket
    ) -> WorkerConnection:
        """注册 Worker 连接"""
        async with self._lock:
            # 如果已存在，先关闭旧连接
            if worker_id in self._workers:
                old_conn = self._workers[worker_id]
                try:
                    await old_conn.websocket.close()
                except Exception:
                    pass
            
            connection = WorkerConnection(
                worker_id=worker_id,
                websocket=websocket
            )
            self._workers[worker_id] = connection
            logger.info(f"Worker 已注册: {worker_id}")
            return connection
    
    async def unregister_worker(self, worker_id: str) -> None:
        """注销 Worker 连接"""
        async with self._lock:
            if worker_id in self._workers:
                del self._workers[worker_id]
                logger.info(f"Worker 已注销: {worker_id}")
    
    async def update_heartbeat(self, worker_id: str) -> None:
        """更新心跳时间"""
        if worker_id in self._workers:
            self._workers[worker_id].last_heartbeat = datetime.now()
    
    async def get_available_worker(self) -> WorkerConnection | None:
        """获取一个可用的 Worker"""
        async with self._lock:
            for worker in self._workers.values():
                if worker.is_alive:
                    return worker
            return None
    
    async def send_request(
        self,
        action: str,
        payload: dict,
        timeout: float = 30.0
    ) -> dict:
        """
        发送请求到 Worker 并等待响应
        
        Args:
            action: 动作类型 (send_message, upload_image, etc.)
            payload: 请求参数
            timeout: 超时时间（秒）
        
        Returns:
            Worker 返回的响应
        
        Raises:
            Exception: 没有可用的 Worker 或请求超时
        """
        worker = await self.get_available_worker()
        if not worker:
            raise Exception("没有可用的 Worker 连接")
        
        # 创建请求
        request_id, future = storage.create_request(action, payload, timeout)
        
        # 构造消息
        message = {
            "type": "request",
            "id": request_id,
            "action": action,
            "payload": payload
        }
        
        try:
            # 发送请求
            await worker.websocket.send_json(message)
            logger.info(f"已发送请求到 Worker: {request_id}, action={action}")
            
            # 等待响应
            response = await asyncio.wait_for(future, timeout=timeout)
            return response
            
        except asyncio.TimeoutError:
            storage.fail_request(request_id, "Request timeout")
            raise Exception(f"请求超时: {request_id}")
        except Exception as e:
            storage.fail_request(request_id, str(e))
            raise
    
    async def handle_message(
        self,
        worker_id: str,
        message: dict
    ) -> None:
        """
        处理来自 Worker 的消息
        """
        msg_type = message.get("type")
        
        if msg_type == "pong":
            # 心跳响应
            await self.update_heartbeat(worker_id)
            
        elif msg_type == "response":
            # 请求响应
            request_id = message.get("id")
            if request_id:
                success = message.get("success", False)
                data = message.get("data", {})
                error = message.get("error")
                
                if success:
                    storage.complete_request(request_id, data)
                else:
                    storage.fail_request(request_id, error or "Unknown error")
                    
        elif msg_type == "callback":
            # 回调事件（用户回复）
            event = message.get("event")
            data = message.get("data", {})
            await self._handle_callback(event, data)
            
        else:
            logger.warning(f"未知消息类型: {msg_type}")
    
    async def _handle_callback(self, event: str, data: dict) -> None:
        """处理回调事件（由 Worker 转发的飞鸽回调）"""
        if event == "wecom_callback":
            # Worker 转发的原始飞鸽回调数据
            callback_data = data.get("callback_data", {})
            
            # 使用 storage 的回调处理逻辑
            result = await storage.handle_callback(callback_data)
            
            if result.get("success"):
                logger.info(f"回调处理成功: session_id={result.get('session_id')}, method={result.get('match_method')}")
            else:
                error = result.get("error", "unknown")
                chat_id = result.get("chat_id") or callback_data.get("chatid", "")
                chat_type = callback_data.get("chattype", "group")
                from_user = callback_data.get("from", {})
                
                if error == "no_waiting_session":
                    logger.warning(f"未找到等待中的会话: chat_id={chat_id}")
                    # 让 Worker 发送 Chat ID 提示
                    await self._send_chat_id_hint(chat_id, chat_type, from_user)
                elif error.startswith("multiple_sessions"):
                    logger.warning(f"多个等待中的会话，需要用户引用回复")
                    # 注意：storage 返回的键是 waiting_sessions
                    sessions = result.get("waiting_sessions", [])
                    await self._send_multiple_sessions_hint(chat_id, sessions, from_user)
                else:
                    logger.warning(f"回调处理失败: {error}")
        else:
            logger.warning(f"未知回调事件: {event}")
    
    async def _send_chat_id_hint(self, chat_id: str, chat_type: str, from_user: dict) -> None:
        """让 Worker 发送 Chat ID 提示"""
        from datetime import datetime
        
        user_name = from_user.get("name", "用户")
        type_desc = "私聊" if chat_type == "single" else "群聊"
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        message = f"""👋 你好 {user_name}！

当前没有等待中的会话需要你回复。

如果你想配置 MCP 使用此{type_desc}，请使用以下信息：

📋 **Chat ID**: `{chat_id}`
📌 **会话类型**: {type_desc}
🕐 **时间**: {timestamp}

你可以将此 Chat ID 配置到 MCP 的环境变量中：
```
DEFAULT_CHAT_ID={chat_id}
```"""
        
        try:
            await self.send_request(
                action="send_hint",
                payload={
                    "chat_id": chat_id,
                    "message": message,
                    "msg_type": "markdown"
                },
                timeout=10.0
            )
            logger.info(f"已发送 Chat ID 提示: chat_id={chat_id}")
        except Exception as e:
            logger.error(f"发送 Chat ID 提示失败: {e}")
    
    async def _send_multiple_sessions_hint(self, chat_id: str, sessions: list, from_user: dict) -> None:
        """让 Worker 发送多会话提示"""
        user_name = from_user.get("name", "用户")
        
        # 构建会话列表
        session_list = []
        for i, session in enumerate(sessions[:5], 1):
            project_info = f" ({session.get('project_name', '')})" if session.get('project_name') else ""
            msg = session.get('message', '')
            short_msg = msg[:30] + "..." if len(msg) > 30 else msg
            session_list.append(f"{i}. `[#{session.get('short_id', '')}]`{project_info}: {short_msg}")
        
        sessions_text = "\n".join(session_list)
        
        message = f"""⚠️ {user_name}，检测到 {len(sessions)} 个等待回复的消息：

{sessions_text}

请使用「**引用回复**」功能选择要回复的消息，这样我才能准确匹配！

（长按或右键消息 → 选择"引用"或"回复"）"""
        
        try:
            await self.send_request(
                action="send_hint",
                payload={
                    "chat_id": chat_id,
                    "message": message,
                    "msg_type": "markdown"
                },
                timeout=10.0
            )
            logger.info(f"已发送多会话提示: chat_id={chat_id}")
        except Exception as e:
            logger.error(f"发送多会话提示失败: {e}")
    
    async def broadcast_ping(self) -> None:
        """向所有 Worker 发送心跳"""
        async with self._lock:
            for worker in list(self._workers.values()):
                try:
                    await worker.websocket.send_json({"type": "ping"})
                    logger.debug(f"已发送心跳 ping 到 Worker: {worker.worker_id}")
                except Exception as e:
                    logger.warning(f"发送心跳失败: {worker.worker_id}, {e}")
                    worker.is_alive = False
    
    async def check_heartbeat(self) -> None:
        """检查心跳超时"""
        now = datetime.now()
        timeout = config.heartbeat_timeout
        
        async with self._lock:
            for worker_id, worker in list(self._workers.items()):
                elapsed = (now - worker.last_heartbeat).total_seconds()
                if elapsed > timeout:
                    logger.warning(f"Worker 心跳超时: {worker_id}")
                    worker.is_alive = False
                    try:
                        await worker.websocket.close()
                    except Exception:
                        pass
                    del self._workers[worker_id]


# 全局管理器实例
ws_manager = WebSocketManager()
