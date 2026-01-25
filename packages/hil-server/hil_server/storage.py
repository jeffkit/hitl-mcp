"""
Relay Server 存储模块

完整的会话管理，包括：
1. 待处理的请求（等待 Worker 响应）
2. 会话数据（等待用户回复）
3. 回调匹配逻辑

支持数据库持久化（可选）
"""
import asyncio
import uuid
import re
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import Any

from sqlalchemy import select, update, and_
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)

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
    """
    Relay Server 存储管理器
    
    支持两种模式：
    1. 内存模式（默认）：会话存储在内存中，重启丢失
    2. 数据库模式：会话持久化到数据库，重启后可恢复
    
    设置环境变量 HIL_USE_DATABASE=true 启用数据库模式
    """
    
    def __init__(self, use_database: bool = False):
        # 待处理的请求 (request_id -> PendingRequest)
        self._pending_requests: dict[str, PendingRequest] = {}
        # 会话数据 (session_id -> Session) - 内存缓存
        self._sessions: dict[str, Session] = {}
        # short_id -> session_id 映射
        self._short_id_map: dict[str, str] = {}
        # chat_id -> list[session_id] 映射（同一个 chat 可能有多个等待中的会话）
        self._chat_id_map: dict[str, list[str]] = {}
        self._lock = asyncio.Lock()
        
        # 数据库模式
        self._use_database = use_database
        self._db_manager = None
    
    async def init_database(self):
        """初始化数据库连接"""
        if not self._use_database:
            return
        
        from .database import init_database, get_db_manager
        from .models import HILSession
        
        await init_database()
        self._db_manager = get_db_manager()
        
        # 从数据库加载等待中的会话到内存缓存
        await self._load_waiting_sessions()
        logger.info("数据库模式已启用，等待中的会话已加载到内存")
    
    async def _load_waiting_sessions(self):
        """从数据库加载等待中的会话"""
        if not self._db_manager:
            return
        
        from .models import HILSession
        
        async with self._db_manager.session() as db:
            result = await db.execute(
                select(HILSession)
                .where(
                    and_(
                        HILSession.status == "waiting",
                        HILSession.expire_at > datetime.now()
                    )
                )
                .options(selectinload(HILSession.replies))
            )
            db_sessions = result.scalars().all()
            
            for db_session in db_sessions:
                session = Session(
                    session_id=db_session.session_id,
                    short_id=db_session.short_id,
                    chat_id=db_session.chat_id,
                    chat_type=db_session.chat_type,
                    message=db_session.message,
                    project_name=db_session.project_name,
                    images=db_session.images or [],
                    status=db_session.status,
                    replies=[r.to_dict() for r in db_session.replies],
                    created_at=db_session.created_at,
                    expire_at=db_session.expire_at
                )
                
                self._sessions[session.session_id] = session
                self._short_id_map[session.short_id] = session.session_id
                
                if session.chat_id not in self._chat_id_map:
                    self._chat_id_map[session.chat_id] = []
                self._chat_id_map[session.chat_id].append(session.session_id)
            
            logger.info(f"从数据库加载了 {len(db_sessions)} 个等待中的会话")
    
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
            expire_at = datetime.now() + timedelta(seconds=timeout)
            
            session = Session(
                session_id=session_id,
                short_id=short_id,
                chat_id=chat_id,
                chat_type=chat_type,
                message=message,
                project_name=project_name,
                images=images or [],
                expire_at=expire_at
            )
            
            # 保存到数据库（如果启用）
            if self._db_manager:
                from .models import HILSession
                async with self._db_manager.session() as db:
                    db_session = HILSession(
                        session_id=session_id,
                        short_id=short_id,
                        chat_id=chat_id,
                        chat_type=chat_type,
                        message=message,
                        project_name=project_name,
                        images=images or [],
                        status="waiting",
                        expire_at=expire_at
                    )
                    db.add(db_session)
            
            # 添加到内存缓存
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
    
    async def get_session_by_short_id(self, short_id: str, chat_id: str | None = None) -> Session | None:
        """
        通过 short_id 获取等待中的会话
        
        Args:
            short_id: 会话短 ID
            chat_id: 可选，限定在该 chat_id 中查找
        """
        session_id = self._short_id_map.get(short_id)
        if session_id:
            session = await self.get_session(session_id)
            if session and session.status == "waiting":
                # 如果指定了 chat_id，检查是否匹配
                if chat_id is None or session.chat_id == chat_id:
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
            
            reply_dict = asdict(reply)
            session.replies.append(reply_dict)
            session.status = "replied"
            
            # 更新数据库（如果启用）
            if self._db_manager:
                from .models import HILSession, HILReply
                async with self._db_manager.session() as db:
                    # 更新会话状态
                    await db.execute(
                        update(HILSession)
                        .where(HILSession.session_id == session_id)
                        .values(status="replied", updated_at=datetime.now())
                    )
                    
                    # 添加回复记录
                    db_reply = HILReply(
                        session_id=session_id,
                        msg_type=reply.msg_type,
                        content=reply.content,
                        image_url=reply.image_url,
                        from_user=reply.from_user,
                        raw_data=reply.raw_data,
                        timestamp=datetime.fromisoformat(reply.timestamp) if isinstance(reply.timestamp, str) else reply.timestamp
                    )
                    db.add(db_reply)
            
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
            
            # 更新数据库（如果启用）
            if self._db_manager:
                from .models import HILSession
                async with self._db_manager.session() as db:
                    await db.execute(
                        update(HILSession)
                        .where(HILSession.session_id == session_id)
                        .values(status="timeout", updated_at=datetime.now())
                    )
            
            # 清理映射
            self._short_id_map.pop(session.short_id, None)
            if session.chat_id in self._chat_id_map:
                try:
                    self._chat_id_map[session.chat_id].remove(session_id)
                except ValueError:
                    pass
            
            return True
    
    async def update_chat_type(self, session_id: str, chat_type: str) -> bool:
        """
        更新会话的 chat_type
        
        当企微回调返回真实的 chattype 时，更新会话中的 chat_type
        """
        async with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False
            
            # 如果 chat_type 没有变化，跳过更新
            if session.chat_type == chat_type:
                return True
            
            logger.info(f"更新会话 chat_type: {session_id[:8]} {session.chat_type} -> {chat_type}")
            session.chat_type = chat_type
            
            # 更新数据库（如果启用）
            if self._db_manager:
                from .models import HILSession
                async with self._db_manager.session() as db:
                    await db.execute(
                        update(HILSession)
                        .where(HILSession.session_id == session_id)
                        .values(chat_type=chat_type, updated_at=datetime.now())
                    )
            
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
        chat_type = data.get("chattype", "group")  # 从回调中获取真实的 chat_type
        
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
            # 更新 chat_type（使用回调中的真实值）
            await self.update_chat_type(session.session_id, chat_type)
            # 添加回复
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
            
            # 清理过期的会话（内存）
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
            
            # 清理过期的会话（数据库）
            if self._db_manager and expired_sessions:
                from .models import HILSession
                async with self._db_manager.session() as db:
                    await db.execute(
                        update(HILSession)
                        .where(
                            and_(
                                HILSession.status == "waiting",
                                HILSession.expire_at < now
                            )
                        )
                        .values(status="expired", updated_at=now)
                    )
    
    async def get_all_sessions(self, limit: int = 100, offset: int = 0) -> list[dict]:
        """
        获取所有会话（用于管理台展示）
        
        优先从数据库获取，否则从内存获取
        """
        if self._db_manager:
            from .models import HILSession
            async with self._db_manager.session() as db:
                result = await db.execute(
                    select(HILSession)
                    .options(selectinload(HILSession.replies))
                    .order_by(HILSession.created_at.desc())
                    .limit(limit)
                    .offset(offset)
                )
                db_sessions = result.scalars().all()
                return [s.to_dict() for s in db_sessions]
        else:
            sessions = list(self._sessions.values())
            sessions.sort(key=lambda x: x.created_at, reverse=True)
            return [s.to_dict() for s in sessions[offset:offset + limit]]
    
    async def get_session_stats(self) -> dict:
        """获取会话统计信息"""
        if self._db_manager:
            from .models import HILSession
            from sqlalchemy import func
            
            async with self._db_manager.session() as db:
                # 总数
                total_result = await db.execute(select(func.count(HILSession.id)))
                total = total_result.scalar()
                
                # 按状态统计
                stats = {}
                for status in ["waiting", "replied", "timeout", "expired"]:
                    result = await db.execute(
                        select(func.count(HILSession.id))
                        .where(HILSession.status == status)
                    )
                    stats[status] = result.scalar()
                
                return {
                    "total": total,
                    "waiting": stats.get("waiting", 0),
                    "replied": stats.get("replied", 0),
                    "timeout": stats.get("timeout", 0),
                    "expired": stats.get("expired", 0),
                }
        else:
            sessions = list(self._sessions.values())
            return {
                "total": len(sessions),
                "waiting": len([s for s in sessions if s.status == "waiting"]),
                "replied": len([s for s in sessions if s.status == "replied"]),
                "timeout": len([s for s in sessions if s.status == "timeout"]),
                "expired": 0,
            }


import os

# 检查是否启用数据库模式
USE_DATABASE = os.getenv("HIL_USE_DATABASE", "").lower() in ("1", "true", "yes")

# 全局存储实例
storage = RelayStorage(use_database=USE_DATABASE)
