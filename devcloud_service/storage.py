"""
会话存储模块

使用 JSONL 文件存储会话数据
"""
import json
import uuid
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from dataclasses import dataclass, asdict, field

from .config import config


@dataclass
class Reply:
    """用户回复"""
    msg_type: str  # text, image, mixed
    content: str | None = None  # 文本内容
    image_url: str | None = None  # 图片 URL
    from_user: dict = field(default_factory=dict)  # 发送者信息
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    raw_data: dict = field(default_factory=dict)  # 原始回调数据


@dataclass
class Session:
    """会话"""
    session_id: str
    chat_id: str  # 群 ID 或 个人会话 ID
    chat_type: str  # group 或 single
    message: str  # 发送的消息
    project_name: str = ""  # 项目名称，用于标识消息来源
    short_id: str = ""  # 短会话 ID（session_id 前 8 位），用于消息中显示
    images: list[str] = field(default_factory=list)  # 发送的图片
    status: str = "waiting"  # waiting, replied, timeout, error
    replies: list[dict] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    expire_at: str = field(default_factory=lambda: (
        datetime.now() + timedelta(seconds=config.session_expire_seconds)
    ).isoformat())
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> "Session":
        # 处理 replies 字段
        replies = data.get("replies", [])
        session_id = data["session_id"]
        return cls(
            session_id=session_id,
            chat_id=data["chat_id"],
            chat_type=data.get("chat_type", "group"),
            message=data["message"],
            project_name=data.get("project_name", ""),
            short_id=data.get("short_id", session_id[:8] if session_id else ""),
            images=data.get("images", []),
            status=data.get("status", "waiting"),
            replies=replies,
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
            expire_at=data.get("expire_at", (
                datetime.now() + timedelta(seconds=config.session_expire_seconds)
            ).isoformat())
        )


class SessionStorage:
    """会话存储管理器"""
    
    def __init__(self, data_dir: Path | None = None):
        self.data_dir = data_dir or config.ensure_data_dir()
        self.sessions_file = self.data_dir / "sessions.jsonl"
        self._lock = asyncio.Lock()
        # 内存缓存，用于快速查找
        self._cache: dict[str, Session] = {}
        self._chat_id_to_session: dict[str, str] = {}  # chat_id -> session_id
        self._short_id_to_session: dict[str, str] = {}  # short_id -> session_id
    
    async def _load_sessions(self) -> dict[str, Session]:
        """从文件加载会话"""
        sessions = {}
        if not self.sessions_file.exists():
            return sessions
        
        try:
            with open(self.sessions_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        session = Session.from_dict(data)
                        # 检查是否过期
                        if datetime.fromisoformat(session.expire_at) > datetime.now():
                            sessions[session.session_id] = session
                    except (json.JSONDecodeError, KeyError):
                        continue
        except Exception:
            pass
        
        return sessions
    
    async def _save_sessions(self) -> None:
        """保存会话到文件"""
        async with self._lock:
            # 过滤过期的会话
            now = datetime.now()
            valid_sessions = {
                sid: s for sid, s in self._cache.items()
                if datetime.fromisoformat(s.expire_at) > now
            }
            self._cache = valid_sessions
            
            # 写入文件
            with open(self.sessions_file, "w", encoding="utf-8") as f:
                for session in valid_sessions.values():
                    f.write(json.dumps(session.to_dict(), ensure_ascii=False) + "\n")
    
    async def init(self) -> None:
        """初始化存储"""
        self._cache = await self._load_sessions()
        # 重建 chat_id 和 short_id 到 session_id 的映射
        for session in self._cache.values():
            if session.status == "waiting":
                self._chat_id_to_session[session.chat_id] = session.session_id
                if session.short_id:
                    self._short_id_to_session[session.short_id] = session.session_id
    
    async def create_session(
        self,
        chat_id: str,
        chat_type: str,
        message: str,
        images: list[str] | None = None,
        project_name: str = ""
    ) -> Session:
        """创建新会话"""
        session_id = str(uuid.uuid4())
        short_id = session_id[:8]  # 短 ID 用于消息中显示
        session = Session(
            session_id=session_id,
            chat_id=chat_id,
            chat_type=chat_type,
            message=message,
            project_name=project_name,
            short_id=short_id,
            images=images or []
        )
        
        self._cache[session_id] = session
        # 同时建立 short_id 的映射
        self._short_id_to_session[short_id] = session_id
        self._chat_id_to_session[chat_id] = session_id
        await self._save_sessions()
        
        return session
    
    async def get_session(self, session_id: str) -> Session | None:
        """获取会话"""
        session = self._cache.get(session_id)
        if session and datetime.fromisoformat(session.expire_at) > datetime.now():
            return session
        return None
    
    async def get_session_by_chat_id(self, chat_id: str) -> Session | None:
        """根据 chat_id 获取等待中的会话（仅当只有一个时返回）"""
        sessions = await self.get_waiting_sessions_by_chat_id(chat_id)
        if len(sessions) == 1:
            return sessions[0]
        return None
    
    async def get_waiting_sessions_by_chat_id(self, chat_id: str) -> list[Session]:
        """根据 chat_id 获取所有等待中的会话（过滤已过期的）"""
        now = datetime.now()
        waiting_sessions = []
        for session in self._cache.values():
            if (session.chat_id == chat_id and 
                session.status == "waiting" and
                datetime.fromisoformat(session.expire_at) > now):
                waiting_sessions.append(session)
        # 按创建时间排序（最新的在前）
        waiting_sessions.sort(key=lambda s: s.created_at, reverse=True)
        return waiting_sessions
    
    async def get_session_by_short_id(self, short_id: str) -> Session | None:
        """根据 short_id 获取等待中的会话"""
        session_id = self._short_id_to_session.get(short_id)
        if session_id:
            session = await self.get_session(session_id)
            if session and session.status == "waiting":
                return session
        return None
    
    async def add_reply(
        self,
        session_id: str,
        reply: Reply
    ) -> bool:
        """添加回复到会话"""
        session = await self.get_session(session_id)
        if not session:
            return False
        
        session.replies.append(asdict(reply))
        session.status = "replied"
        session.updated_at = datetime.now().isoformat()
        
        # 清理映射
        if session.chat_id in self._chat_id_to_session:
            del self._chat_id_to_session[session.chat_id]
        if session.short_id in self._short_id_to_session:
            del self._short_id_to_session[session.short_id]
        
        await self._save_sessions()
        return True
    
    async def add_reply_by_chat_id(
        self,
        chat_id: str,
        reply: Reply
    ) -> bool:
        """根据 chat_id 添加回复"""
        session = await self.get_session_by_chat_id(chat_id)
        if not session:
            return False
        return await self.add_reply(session.session_id, reply)
    
    async def add_reply_by_short_id(
        self,
        short_id: str,
        reply: Reply
    ) -> bool:
        """根据 short_id 添加回复（用于引用消息匹配）"""
        session = await self.get_session_by_short_id(short_id)
        if not session:
            return False
        return await self.add_reply(session.session_id, reply)
    
    async def mark_timeout(self, session_id: str) -> bool:
        """标记会话超时"""
        session = await self.get_session(session_id)
        if not session:
            return False
        
        session.status = "timeout"
        session.updated_at = datetime.now().isoformat()
        
        # 清理映射
        if session.chat_id in self._chat_id_to_session:
            del self._chat_id_to_session[session.chat_id]
        if session.short_id in self._short_id_to_session:
            del self._short_id_to_session[session.short_id]
        
        await self._save_sessions()
        return True


# 全局存储实例
storage = SessionStorage()
