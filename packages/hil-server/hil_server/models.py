"""
HIL Server 数据库模型

用于持久化会话数据
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, 
    JSON, ForeignKey, Index, Enum
)
from sqlalchemy.orm import relationship, declarative_base
import enum

Base = declarative_base()


class SessionStatus(str, enum.Enum):
    """会话状态"""
    WAITING = "waiting"
    REPLIED = "replied"
    TIMEOUT = "timeout"
    EXPIRED = "expired"


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
