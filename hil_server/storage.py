"""
Relay Server 存储模块

完整的会话管理，包括：
1. 待处理的请求（等待 Worker 响应）
2. 会话数据（等待用户回复）
3. 回调匹配逻辑
"""
import asyncio
import uuid
import re
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import Any

# 匹配消息中的会话标识 [#short_id] 或 [#short_id 项目名]
SESSION_ID_PATTERN = re.compile(r'\[#([a-f0-9]{8})(?:\s+[^\]]+)?\]')


@dataclass
class Reply:
    """用户回复"""
    msg_type: str  # text, image, mixed
    content: str | None = None
    image_url: str | None = None
    from_user: dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    raw_data: dict = field(default_factory=dict)


@dataclass
class PendingRequest:
    """待处理的请求（等待 Worker 响应）"""
    request_id: str
    action: str
    payload: dict
    future: asyncio.Future
    created_at: datetime = field(default_factory=datetime.now)
    timeout: float = 30.0


@dataclass
class Session:
    """会话数据"""
    session_id: str
    short_id: str  # session_id 前 8 位，用于消息标识
    chat_id: str
    chat_type: str = "group"
    message: str = ""
    project_name: str = ""
    images: list[str] = field(default_factory=list)
    status: str = "waiting"  # waiting, replied, timeout
    replies: list[dict] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    expire_at: datetime = field(default_factory=lambda: datetime.now() + timedelta(hours=1))
    
    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "short_id": self.short_id,
            "chat_id": self.chat_id,
            "chat_type": self.chat_type,
            "message": self.message,
            "project_name": self.project_name,
            "status": self.status,
            "replies": self.replies,
            "created_at": self.created_at.isoformat(),
            "expire_at": self.expire_at.isoformat(),
        }


def parse_quoted_message(content: str) -> tuple[str | None, str]:
    """
    解析引用消息，提取 short_id 和实际回复内容
    
    企业微信引用消息格式:
    "发送者名称：
    被引用的消息内容..."
    ------
    @机器人 用户的实际回复
    
    Returns:
        (short_id, actual_reply)
    """
    left_quote = '\u201c'  # "
    right_quote = '\u201d'  # "
    if not (content.startswith(left_quote) or content.startswith(right_quote)):
        return None, content
    
    separator = "------"
    if separator not in content:
        return None, content
    
    parts = content.split(separator, 1)
    quoted_part = parts[0]
    reply_part = parts[1].strip() if len(parts) > 1 else ""
    
    # 从引用部分提取 short_id
    match = SESSION_ID_PATTERN.search(quoted_part)
    short_id = match.group(1) if match else None
    
    # 清理回复部分（去除 @机器人）
    if reply_part.startswith("@"):
        space_idx = reply_part.find(" ")
        if space_idx > 0:
            reply_part = reply_part[space_idx + 1:].strip()
    
    return short_id, reply_part


def extract_reply_from_callback(data: dict) -> tuple[Reply, str | None]:
    """
    从飞鸽回调数据中提取回复信息
    
    Returns:
        (Reply, short_id)
    """
    msg_type = data.get("msgtype", "text")
    from_user = data.get("from", {})
    
    content = None
    image_url = None
    short_id = None
    
    if msg_type == "text":
        text_data = data.get("text", {})
        raw_content = text_data.get("content", "")
        
        short_id, content = parse_quoted_message(raw_content)
        
        if short_id is None and content == raw_content:
            if content.startswith("@"):
                parts = content.split(" ", 1)
                if len(parts) > 1:
                    content = parts[1].strip()
    
    elif msg_type == "image":
        image_data = data.get("image", {})
        image_url = image_data.get("image_url", "")
    
    elif msg_type == "mixed":
        mixed = data.get("mixed_message", {})
        msg_items = mixed.get("msg_item", [])
        
        contents = []
        images = []
        
        for item in msg_items:
            item_type = item.get("msg_type", "")
            if item_type == "text":
                text = item.get("text", {}).get("content", "")
                item_short_id, parsed_text = parse_quoted_message(text)
                if item_short_id:
                    short_id = item_short_id
                    text = parsed_text
                elif text.startswith("@"):
                    parts = text.split(" ", 1)
                    if len(parts) > 1:
                        text = parts[1].strip()
                if text:
                    contents.append(text)
            elif item_type == "image":
                img_url = item.get("image", {}).get("image_url", "")
                if img_url:
                    images.append(img_url)
        
        content = "\n".join(contents) if contents else None
        image_url = images[0] if images else None
    
    reply = Reply(
        msg_type=msg_type,
        content=content,
        image_url=image_url,
        from_user=from_user,
        raw_data=data
    )
    
    return reply, short_id


class RelayStorage:
    """Relay Server 存储管理器"""
    
    def __init__(self):
        # 待处理的请求 (request_id -> PendingRequest)
        self._pending_requests: dict[str, PendingRequest] = {}
        # 会话数据 (session_id -> Session)
        self._sessions: dict[str, Session] = {}
        # short_id -> session_id 映射
        self._short_id_map: dict[str, str] = {}
        # chat_id -> list[session_id] 映射（同一个 chat 可能有多个等待中的会话）
        self._chat_id_map: dict[str, list[str]] = {}
        self._lock = asyncio.Lock()
    
    # ========== 请求管理 ==========
    
    def create_request(
        self,
        action: str,
        payload: dict,
        timeout: float = 30.0
    ) -> tuple[str, asyncio.Future]:
        """创建一个待处理的请求"""
        request_id = str(uuid.uuid4())
        future = asyncio.get_event_loop().create_future()
        
        request = PendingRequest(
            request_id=request_id,
            action=action,
            payload=payload,
            future=future,
            timeout=timeout
        )
        
        self._pending_requests[request_id] = request
        return request_id, future
    
    def complete_request(self, request_id: str, response: dict) -> bool:
        """完成一个请求"""
        request = self._pending_requests.pop(request_id, None)
        if request and not request.future.done():
            request.future.set_result(response)
            return True
        return False
    
    def fail_request(self, request_id: str, error: str) -> bool:
        """标记请求失败"""
        request = self._pending_requests.pop(request_id, None)
        if request and not request.future.done():
            request.future.set_exception(Exception(error))
            return True
        return False
    
    # ========== 会话管理 ==========
    
    async def create_session(
        self,
        chat_id: str,
        chat_type: str = "group",
        message: str = "",
        project_name: str = "",
        images: list[str] | None = None,
        timeout: int = 300
    ) -> Session:
        """创建会话"""
        async with self._lock:
            session_id = str(uuid.uuid4())
            short_id = session_id[:8]
            
            session = Session(
                session_id=session_id,
                short_id=short_id,
                chat_id=chat_id,
                chat_type=chat_type,
                message=message,
                project_name=project_name,
                images=images or [],
                expire_at=datetime.now() + timedelta(seconds=timeout)
            )
            
            self._sessions[session_id] = session
            self._short_id_map[short_id] = session_id
            
            if chat_id not in self._chat_id_map:
                self._chat_id_map[chat_id] = []
            self._chat_id_map[chat_id].append(session_id)
            
            return session
    
    async def get_session(self, session_id: str) -> Session | None:
        """获取会话"""
        session = self._sessions.get(session_id)
        if session and session.expire_at > datetime.now():
            return session
        return None
    
    async def get_session_by_short_id(self, short_id: str) -> Session | None:
        """通过 short_id 获取等待中的会话"""
        session_id = self._short_id_map.get(short_id)
        if session_id:
            session = await self.get_session(session_id)
            if session and session.status == "waiting":
                return session
        return None
    
    async def get_waiting_sessions_by_chat_id(self, chat_id: str) -> list[Session]:
        """获取某个 chat_id 下所有等待中的会话"""
        now = datetime.now()
        sessions = []
        for session_id in self._chat_id_map.get(chat_id, []):
            session = self._sessions.get(session_id)
            if session and session.status == "waiting" and session.expire_at > now:
                sessions.append(session)
        return sessions
    
    async def add_reply(self, session_id: str, reply: Reply) -> bool:
        """添加回复到会话"""
        async with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False
            
            session.replies.append(asdict(reply))
            session.status = "replied"
            
            # 清理映射
            self._short_id_map.pop(session.short_id, None)
            if session.chat_id in self._chat_id_map:
                try:
                    self._chat_id_map[session.chat_id].remove(session_id)
                except ValueError:
                    pass
            
            return True
    
    async def mark_timeout(self, session_id: str) -> bool:
        """标记会话超时"""
        async with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False
            
            session.status = "timeout"
            
            # 清理映射
            self._short_id_map.pop(session.short_id, None)
            if session.chat_id in self._chat_id_map:
                try:
                    self._chat_id_map[session.chat_id].remove(session_id)
                except ValueError:
                    pass
            
            return True
    
    # ========== 回调处理 ==========
    
    async def handle_callback(self, data: dict) -> dict:
        """
        处理飞鸽回调（由 Worker 转发过来）
        
        Returns:
            {"success": bool, "session_id": str | None, "error": str | None}
        """
        chat_id = data.get("chatid", "")
        msg_type = data.get("msgtype", "")
        
        # 忽略某些事件类型
        if msg_type in ("event", "enter_chat"):
            return {"success": True, "session_id": None, "error": None}
        
        # 提取回复
        reply, short_id = extract_reply_from_callback(data)
        
        session = None
        match_method = None
        
        # 优先使用 short_id 匹配
        if short_id:
            session = await self.get_session_by_short_id(short_id)
            if session:
                match_method = f"short_id={short_id}"
        
        # 回退到 chat_id 匹配
        if not session:
            waiting_sessions = await self.get_waiting_sessions_by_chat_id(chat_id)
            if len(waiting_sessions) == 1:
                session = waiting_sessions[0]
                match_method = f"chat_id={chat_id}"
            elif len(waiting_sessions) > 1:
                # 多个等待中的会话
                return {
                    "success": False,
                    "session_id": None,
                    "error": f"multiple_sessions:{len(waiting_sessions)}",
                    "waiting_sessions": [s.to_dict() for s in waiting_sessions]
                }
        
        if session:
            await self.add_reply(session.session_id, reply)
            return {
                "success": True,
                "session_id": session.session_id,
                "match_method": match_method
            }
        else:
            return {
                "success": False,
                "session_id": None,
                "error": "no_waiting_session",
                "chat_id": chat_id
            }
    
    # ========== 清理 ==========
    
    async def cleanup_expired(self) -> None:
        """清理过期的数据"""
        async with self._lock:
            now = datetime.now()
            
            # 清理过期的请求
            expired_requests = [
                rid for rid, req in self._pending_requests.items()
                if (now - req.created_at).total_seconds() > req.timeout
            ]
            for rid in expired_requests:
                self.fail_request(rid, "Request timeout")
            
            # 清理过期的会话
            expired_sessions = [
                sid for sid, s in self._sessions.items()
                if s.expire_at < now
            ]
            for sid in expired_sessions:
                session = self._sessions.pop(sid, None)
                if session:
                    self._short_id_map.pop(session.short_id, None)
                    if session.chat_id in self._chat_id_map:
                        try:
                            self._chat_id_map[session.chat_id].remove(sid)
                        except ValueError:
                            pass


# 全局存储实例
storage = RelayStorage()
