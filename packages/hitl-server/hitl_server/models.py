"""
HITL Server 数据库模型

用于持久化会话数据
"""
from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, 
    JSON, ForeignKey, Index, Enum
)
from sqlalchemy.orm import relationship, declarative_base, Mapped, mapped_column
from typing import Optional
import enum

Base = declarative_base()


class SessionStatus(str, enum.Enum):
    """会话状态"""
    WAITING = "waiting"
    REPLIED = "replied"
    TIMEOUT = "timeout"
    EXPIRED = "expired"


class ChatInfo(Base):
    """
    Chat 信息表
    
    用于存储 chat_id 到 chat_type 的映射：
    - 首次收到某 chat_id 的回调时自动记录
    - 用于在发送消息时判断目标类型（群聊/私聊）
    - 不同 chat_type 有不同的消息条数限制
    """
    __tablename__ = "chat_info"
    
    # 主键
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    
    # Chat ID (唯一)
    chat_id: Mapped[str] = mapped_column(
        String(200),
        unique=True,
        nullable=False,
        index=True,
        comment="Chat ID (群ID或私聊ID)"
    )
    
    # Chat 类型
    chat_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="group",
        comment="Chat 类型: group (群聊) / single (私聊)"
    )
    
    # Chat 名称（可选，用于显示）
    chat_name: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
        comment="Chat 名称（群名/用户名）"
    )
    
    # 关联的 Bot Key（首次收到消息的 Bot）
    first_bot_key: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="首次收到消息的 Bot Key"
    )
    
    # 消息计数
    message_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="收到的消息总数"
    )
    
    # 时间戳
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="首次收到消息的时间"
    )
    
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        comment="最后收到消息的时间"
    )
    
    # 索引
    __table_args__ = (
        Index("idx_chat_info_chat_id", "chat_id"),
        Index("idx_chat_info_chat_type", "chat_type"),
        Index("idx_chat_info_last_seen", "last_seen_at"),
    )


class HILSession(Base):
    """HIL 会话表"""
    __tablename__ = "hil_sessions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(36), unique=True, nullable=False, index=True)
    short_id = Column(String(8), nullable=False, index=True)
    
    # 会话信息
    chat_id = Column(String(255), nullable=False, index=True)
    chat_type = Column(String(20), default="group")
    message = Column(Text, default="")
    project_name = Column(String(255), default="")
    images = Column(JSON, default=list)
    
    # 状态
    status = Column(String(20), default="waiting", index=True)
    
    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    expire_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关联的回复
    replies = relationship("HILReply", back_populates="session", cascade="all, delete-orphan")
    
    # 索引
    __table_args__ = (
        Index("idx_chat_status", "chat_id", "status"),
        Index("idx_expire_status", "expire_at", "status"),
    )
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "session_id": self.session_id,
            "short_id": self.short_id,
            "chat_id": self.chat_id,
            "chat_type": self.chat_type,
            "message": self.message,
            "project_name": self.project_name,
            "images": self.images or [],
            "status": self.status,
            "replies": [r.to_dict() for r in self.replies],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "expire_at": self.expire_at.isoformat() if self.expire_at else None,
        }


class HILReply(Base):
    """会话回复表"""
    __tablename__ = "hil_replies"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(36), ForeignKey("hil_sessions.session_id"), nullable=False, index=True)
    
    # 回复内容
    msg_type = Column(String(20), nullable=False)  # text, image, mixed
    content = Column(Text, nullable=True)
    image_url = Column(String(1024), nullable=True)
    
    # 发送者信息
    from_user = Column(JSON, default=dict)
    
    # 原始数据
    raw_data = Column(JSON, default=dict)
    
    # 时间戳
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    # 关联
    session = relationship("HILSession", back_populates="replies")
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "msg_type": self.msg_type,
            "content": self.content,
            "image_url": self.image_url,
            "from_user": self.from_user or {},
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "raw_data": self.raw_data or {},
        }
