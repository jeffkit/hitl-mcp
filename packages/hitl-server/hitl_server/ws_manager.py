"""
WebSocket 连接管理器

管理与 Worker 的 WebSocket 连接（支持多类型 Worker：fly-pigeon / ilink / wecom-aibot）

路由：
- 每个 Worker 注册时携带 worker_type 与 bot_key
- send_request 可按 bot_key（优先）/ worker_type 路由到对应 Worker
- 用户消息回调（wecom_callback / user_message）统一走 storage.handle_callback
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
from .idle_hint_config import idle_hint_config

logger = logging.getLogger(__name__)


@dataclass
class WorkerConnection:
    """Worker 连接信息"""
    worker_id: str
    websocket: WebSocket
    connected_at: datetime = field(default_factory=datetime.now)
    last_heartbeat: datetime = field(default_factory=datetime.now)
    is_alive: bool = True
    # 扩展信息
    worker_type: str = "fly-pigeon"  # fly-pigeon | ilink | wecom-aibot
    ip_address: str = ""
    hostname: str = ""
    callback_port: int = 0
    bot_key: str = ""  # 部分显示；ilink/wecom-aibot 用作发送路由键
    hil_url: str = ""
    config_file: str = ""
    forward_service_url: str = ""  # 关联的 Forward Service 地址

    def to_dict(self) -> dict:
        """转换为字典（用于 API 返回）"""
        return {
            "worker_id": self.worker_id,
            "worker_type": self.worker_type,
            "ip_address": self.ip_address,
            "hostname": self.hostname,
            "callback_port": self.callback_port,
            "bot_key": self.bot_key,
            "hil_url": self.hil_url,
            "config_file": self.config_file,
            "forward_service_url": self.forward_service_url,
            "connected_at": self.connected_at.isoformat(),
            "last_heartbeat": self.last_heartbeat.isoformat(),
            "is_alive": self.is_alive
        }


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
        websocket: WebSocket,
        worker_info: dict | None = None
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
            
            # 从 worker_info 提取扩展信息
            info = worker_info or {}
            
            connection = WorkerConnection(
                worker_id=worker_id,
                websocket=websocket,
                worker_type=info.get("worker_type", "fly-pigeon"),
                ip_address=info.get("ip_address", ""),
                hostname=info.get("hostname", ""),
                callback_port=info.get("callback_port", 0),
                bot_key=info.get("bot_key", ""),
                hil_url=info.get("hil_url", ""),
                config_file=info.get("config_file", ""),
                forward_service_url=info.get("forward_service_url", "")
            )
            self._workers[worker_id] = connection
            logger.info(
                f"Worker 已注册: {worker_id}, type={connection.worker_type}, "
                f"bot_key={connection.bot_key}, ip={connection.ip_address}"
            )
            return connection
    
    def get_all_workers(self) -> list[dict]:
        """获取所有 Worker 信息（用于管理台）"""
        return [w.to_dict() for w in self._workers.values()]
    
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
    
    async def _update_worker_info(self, worker_id: str, worker_info: dict) -> None:
        """更新 Worker 扩展信息"""
        if worker_id in self._workers:
            worker = self._workers[worker_id]
            worker.worker_type = worker_info.get("worker_type", worker.worker_type)
            worker.ip_address = worker_info.get("ip_address", worker.ip_address)
            worker.hostname = worker_info.get("hostname", worker.hostname)
            worker.callback_port = worker_info.get("callback_port", worker.callback_port)
            worker.bot_key = worker_info.get("bot_key", worker.bot_key)
            worker.hil_url = worker_info.get("hil_url", worker.hil_url)
            worker.config_file = worker_info.get("config_file", worker.config_file)
            worker.forward_service_url = worker_info.get("forward_service_url", worker.forward_service_url)
            logger.info(
                f"Worker 信息已更新: {worker_id}, type={worker.worker_type}, "
                f"ip={worker.ip_address}"
            )

    async def get_available_worker(
        self, bot_key: str | None = None, worker_type: str | None = None
    ) -> WorkerConnection | None:
        """
        获取一个可用的 Worker

        Args:
            bot_key: 指定 bot_key（ilink/wecom-aibot 路由用）；为 None 时走默认（fly-pigeon）。
            worker_type: 可选，进一步限定 worker 类型。
        """
        async with self._lock:
            # 优先精确匹配 bot_key
            if bot_key:
                for worker in self._workers.values():
                    if worker.is_alive and worker.bot_key == bot_key:
                        if worker_type is None or worker.worker_type == worker_type:
                            return worker
            # 回退：取任意存活且类型匹配的 worker
            for worker in self._workers.values():
                if worker.is_alive:
                    if worker_type is None or worker.worker_type == worker_type:
                        return worker
            return None
    
    async def send_request(
        self,
        action: str,
        payload: dict,
        timeout: float = 30.0,
        bot_key: str | None = None,
        worker_type: str | None = None,
    ) -> dict:
        """
        发送请求到 Worker 并等待响应

        Args:
            action: 动作类型 (send_message, upload_image, etc.)
            payload: 请求参数
            timeout: 超时时间（秒）
            bot_key: 指定目标 Worker 的 bot_key（ilink/wecom-aibot 路由用）
            worker_type: 指定目标 Worker 的类型（fly-pigeon | ilink | wecom-aibot）

        Returns:
            Worker 返回的响应

        Raises:
            Exception: 没有可用的 Worker 或请求超时
        """
        worker = await self.get_available_worker(bot_key=bot_key, worker_type=worker_type)
        if not worker:
            raise Exception(
                f"没有可用的 Worker 连接 (bot_key={bot_key}, type={worker_type})"
            )
        
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
        
        elif msg_type == "register":
            # Worker 注册信息更新
            worker_info = message.get("worker_info", {})
            await self._update_worker_info(worker_id, worker_info)
            
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
            # 携带来源 worker 信息，便于回发提示时路由到同一 worker
            worker = self._workers.get(worker_id)
            await self._handle_callback(
                event, data,
                worker_type=message.get("worker_type") or (worker.worker_type if worker else None),
                bot_key=message.get("bot_key") or (worker.bot_key if worker else None),
                worker_id=worker_id,
            )
            
        else:
            logger.warning(f"未知消息类型: {msg_type}")
    
    async def _handle_callback(
        self, event: str, data: dict, worker_type: str | None = None,
        bot_key: str | None = None, worker_id: str | None = None,
    ) -> None:
        """
        处理回调事件

        Args:
            event: 回调事件名（wecom_callback | user_message）
            data: 回调数据
            worker_type: 上报来源 worker 类型（user_message 时由 handle_message 传入）
            bot_key: 上报来源 worker 的 bot_key（用于回发提示时路由）
            worker_id: 上报来源 worker_id（用于回发提示时路由兜底）
        """
        if event == "wecom_callback":
            # Worker 转发的原始飞鸽回调数据
            callback_data = data.get("callback_data", {})
            await self._process_user_callback(callback_data, worker_type, bot_key, worker_id)

        elif event == "user_message":
            # ilink / wecom-aibot Worker 上报的用户消息（已转成 fly-pigeon 兼容结构）
            callback_data = data.get("callback_data", data)
            await self._process_user_callback(callback_data, worker_type, bot_key, worker_id)

        else:
            logger.warning(f"未知回调事件: {event}")

    async def _process_user_callback(
        self, callback_data: dict,
        worker_type: str | None = None, bot_key: str | None = None,
        worker_id: str | None = None,
    ) -> None:
        """统一处理用户消息回调（wecom_callback 与 user_message 共用）"""
        # 使用 storage 的回调处理逻辑
        result = await storage.handle_callback(callback_data)

        if result.get("success"):
            logger.info(
                f"回调处理成功: session_id={result.get('session_id')}, "
                f"method={result.get('match_method')}"
            )
            return

        error = result.get("error", "unknown")
        chat_id = result.get("chat_id") or callback_data.get("chatid", "")
        chat_type = callback_data.get("chattype", "group")
        from_user = callback_data.get("from", {})

        if error == "no_waiting_session":
            logger.warning(f"未找到等待中的会话: chat_id={chat_id}")
            # ilink / wecom-aibot 是 1:1 bot↔用户模型，收件人固定，
            # 不需要也不应向用户推送 "Chat ID 配置提示"（对用户是噪音）。
            # 仅企微群机器人（fly-pigeon / 默认）才发该提示。
            if worker_type in ("ilink", "wecom-aibot"):
                logger.info(f"跳过 chat_id 提示（worker_type={worker_type}）: chat_id={chat_id}")
                return
            await self._send_chat_id_hint(chat_id, chat_type, from_user, bot_key, worker_id)
        elif error.startswith("multiple_sessions"):
            logger.warning(f"多个等待中的会话，需要用户引用回复")
            # ilink / wecom-aibot 回复不带 quote，无法区分多会话，提示也无意义，跳过。
            if worker_type in ("ilink", "wecom-aibot"):
                logger.info(f"跳过多会话提示（worker_type={worker_type}）: chat_id={chat_id}")
                return
            sessions = result.get("waiting_sessions", [])
            await self._send_multiple_sessions_hint(
                chat_id, sessions, from_user, bot_key, worker_id
            )
        else:
            logger.warning(f"回调处理失败: {error}")
    
    async def _send_chat_id_hint(
        self, chat_id: str, chat_type: str, from_user: dict,
        bot_key: str | None = None, worker_id: str | None = None,
    ) -> None:
        """
        让 Worker 发送 Chat ID 提示

        使用 JSON 配置文件，支持热更新和按 chat_id 自定义配置
        """
        from datetime import datetime

        user_name = from_user.get("name", "用户")
        type_desc = "私聊" if chat_type == "single" else "群聊"
        timestamp = datetime.now().strftime("%H:%M:%S")

        # 从配置文件获取并格式化消息（支持热更新）
        message = idle_hint_config.format_message(
            chat_id=chat_id,
            user_name=user_name,
            chat_type=type_desc,
            timestamp=timestamp
        )

        # 如果配置禁用了提示消息，则不发送
        if message is None:
            logger.info(f"提示消息已禁用，跳过发送: chat_id={chat_id}")
            return

        try:
            await self.send_request(
                action="send_hint",
                payload={
                    "chat_id": chat_id,
                    "message": message,
                    "msg_type": "markdown"
                },
                timeout=10.0,
                bot_key=bot_key,
            )
            logger.info(f"已发送 Chat ID 提示: chat_id={chat_id}")
        except Exception as e:
            logger.error(f"发送 Chat ID 提示失败: {e}")

    async def _send_multiple_sessions_hint(
        self, chat_id: str, sessions: list, from_user: dict,
        bot_key: str | None = None, worker_id: str | None = None,
    ) -> None:
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
                timeout=10.0,
                bot_key=bot_key,
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
