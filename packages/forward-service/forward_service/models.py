"""
Forward Service 数据库模型

使用 SQLAlchemy ORM 定义数据库表结构:
- chatbots: 存储 Bot 配置
- chat_access_rules: 存储黑白名单规则

支持多种数据库引擎:
- 开发/测试: SQLite (内存或文件)
- 生产: MySQL
"""
from datetime import datetime
from typing import Optional
try:
    from typing import Literal
except ImportError:
    from typing_extensions import Literal
from sqlalchemy import (
    String, Boolean, Integer, Text, DateTime, ForeignKey,
    Index, UniqueConstraint
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.ext.hybrid import hybrid_property


# ============== Base Class ==============

class Base(DeclarativeBase):
    """所有模型的基类"""
    pass


# ============== 枚举类型定义 ==============

AccessMode = Literal["allow_all", "whitelist", "blacklist"]


# ============== 数据库模型 ==============

class Chatbot(Base):
    """
    Chatbot 配置表

    存储企业微信机器人的配置信息，包括:
    - 基本信息: bot_key, name, description
    - 转发配置: url_template, agent_id, api_key, timeout
    - 访问控制模式: allow_all, whitelist, blacklist
    - 状态: enabled
    """
    __tablename__ = "chatbots"

    # 主键
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Bot Key (企业微信 Webhook Key，唯一标识)
    bot_key: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        index=True,
        comment="企微机器人 Webhook Key (唯一)"
    )

    # 基本信息
    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        default="未命名 Bot",
        comment="Bot 名称"
    )

    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Bot 描述"
    )

    # 转发配置
    url_template: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="转发目标 URL 模板 (支持 {agent_id} 占位符)"
    )

    agent_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        default="",
        comment="Agent ID (用于 URL 模板替换)"
    )

    api_key: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
        default="",
        comment="转发请求的 API Key (可选)"
    )

    timeout: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=60,
        comment="转发请求超时时间 (秒)"
    )

    # 访问控制模式
    access_mode: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="allow_all",
        comment="访问控制模式: allow_all, whitelist, blacklist"
    )

    # 状态
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
        comment="是否启用"
    )

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        comment="创建时间"
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        comment="更新时间"
    )

    # 关系: 一个 Bot 有多个访问规则
    access_rules: Mapped[list["ChatAccessRule"]] = relationship(
        "ChatAccessRule",
        back_populates="chatbot",
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    # 索引
    __table_args__ = (
        Index("idx_chatbots_enabled", "enabled"),
        Index("idx_chatbots_bot_key", "bot_key"),
    )

    def __repr__(self) -> str:
        return f"<Chatbot(id={self.id}, bot_key={self.bot_key[:10]}..., name={self.name})>"

    # ============== Hybird Properties (兼容旧代码) ==============

    @hybrid_property
    def forward_config_url_template(self) -> str:
        """兼容旧的 forward_config.url_template"""
        return self.url_template

    @hybrid_property
    def forward_config_agent_id(self) -> str:
        """兼容旧的 forward_config.agent_id"""
        return self.agent_id or ""

    @hybrid_property
    def forward_config_api_key(self) -> str:
        """兼容旧的 forward_config.api_key"""
        return self.api_key or ""

    @hybrid_property
    def forward_config_timeout(self) -> int:
        """兼容旧的 forward_config.timeout"""
        return self.timeout

    # ============== 实例方法 ==============

    def get_url(self) -> str:
        """获取完整的转发 URL (替换占位符)"""
        return self.url_template.replace("{agent_id}", self.agent_id or "")

    def check_access(self, user_id: str) -> tuple[bool, str]:
        """
        检查用户是否有权限访问此 Bot

        注意: 此方法假设 access_rules 已经预加载 (使用 selectin loading)
        如果没有预加载,应该在查询时使用 options(selectinload(Chatbot.access_rules))

        Args:
            user_id: 用户 ID

        Returns:
            (allowed, reason) - allowed 为 True 表示允许访问
        """
        if not self.enabled:
            return False, "Bot 已禁用"

        if self.access_mode == "allow_all":
            return True, ""

        elif self.access_mode == "whitelist":
            # 检查白名单
            for rule in self.access_rules:
                if rule.rule_type == "whitelist" and rule.chat_id == user_id:
                    return True, ""
            return False, "抱歉，您还没有权限访问此 Bot，如有意向，请联系作者。"

        elif self.access_mode == "blacklist":
            # 检查黑名单
            for rule in self.access_rules:
                if rule.rule_type == "blacklist" and rule.chat_id == user_id:
                    return False, "抱歉，您还没有权限访问此 Bot，如有意向，请联系作者。"
            return True, ""

        return False, "未知的访问控制模式"

    def to_dict(self, include_rules: bool = False) -> dict:
        """
        转换为字典 (用于 API 返回)

        Args:
            include_rules: 是否包含访问规则详情
        """
        data = {
            "id": self.id,
            "bot_key": self.bot_key,
            "name": self.name,
            "description": self.description,
            "forward_config": {
                "url_template": self.url_template,
                "agent_id": self.agent_id,
                "api_key": self.api_key,
                "timeout": self.timeout
            },
            "access_control": {
                "mode": self.access_mode,
                "whitelist": [],
                "blacklist": []
            },
            "enabled": self.enabled,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

        # 添加访问规则
        if include_rules:
            for rule in self.access_rules:
                if rule.rule_type == "whitelist":
                    data["access_control"]["whitelist"].append(rule.chat_id)
                elif rule.rule_type == "blacklist":
                    data["access_control"]["blacklist"].append(rule.chat_id)

        return data


class UserSession(Base):
    """
    用户会话表
    
    记录用户与 Agent 的会话信息，用于：
    - 会话持续性：下次用户上行时带上 session_id
    - 会话管理：支持 /sess, /reset, /change 命令
    """
    __tablename__ = "user_sessions"
    
    # 主键
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    
    # 用户标识
    user_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="用户 ID"
    )
    
    # 会话上下文
    chat_id: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        index=True,
        comment="Chat ID (群ID或私聊ID)"
    )
    
    bot_key: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="关联的 Bot Key"
    )
    
    # Agent 会话 ID
    session_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Agent 返回的 Session ID"
    )
    
    short_id: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        index=True,
        comment="Session ID 短标识 (前8位)"
    )
    
    # 会话信息
    last_message: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        comment="用户最后一条消息 (用于展示)"
    )
    
    message_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="消息计数"
    )
    
    # 状态
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
        comment="是否为当前活跃会话"
    )
    
    # 时间戳
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        comment="创建时间"
    )
    
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        comment="更新时间"
    )
    
    # 索引
    __table_args__ = (
        Index("idx_user_session_active", "user_id", "chat_id", "bot_key", "is_active"),
        Index("idx_user_session_short_id", "user_id", "chat_id", "short_id"),
    )
    
    def __repr__(self) -> str:
        return f"<UserSession(id={self.id}, user={self.user_id[:10]}, session={self.short_id})>"
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "chat_id": self.chat_id,
            "bot_key": self.bot_key,
            "session_id": self.session_id,
            "short_id": self.short_id,
            "last_message": self.last_message,
            "message_count": self.message_count,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ChatAccessRule(Base):
    """
    Chat 访问规则表 (黑白名单)

    存储每个 Bot 的访问控制规则:
    - 白名单: 仅允许特定 chat_id 访问
    - 黑名单: 禁止特定 chat_id 访问

    与 chatbots 表是一对多关系
    """
    __tablename__ = "chat_access_rules"

    # 主键
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # 外键: 关联到 chatbots 表
    chatbot_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("chatbots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联的 Bot ID"
    )

    # Chat ID (用户 ID 或群 ID)
    chat_id: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="Chat ID (用户ID或群ID)"
    )

    # 规则类型
    rule_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="规则类型: whitelist 或 blacklist"
    )

    # 备注 (可选)
    remark: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        comment="备注说明"
    )

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        comment="创建时间"
    )

    # 关系: 一个规则属于一个 Bot
    chatbot: Mapped["Chatbot"] = relationship(
        "Chatbot",
        back_populates="access_rules"
    )

    # 约束: 同一个 Bot 的 chat_id + rule_type 必须唯一
    __table_args__ = (
        UniqueConstraint(
            "chatbot_id", "chat_id", "rule_type",
            name="uq_chatbot_chat_rule"
        ),
        Index("idx_access_rules_chatbot_id", "chatbot_id"),
        Index("idx_access_rules_chat_id", "chat_id"),
        Index("idx_access_rules_rule_type", "rule_type"),
    )

    def __repr__(self) -> str:
        return f"<ChatAccessRule(id={self.id}, chatbot_id={self.chatbot_id}, chat_id={self.chat_id}, type={self.rule_type})>"

    def to_dict(self) -> dict:
        """转换为字典 (用于 API 返回)"""
        return {
            "id": self.id,
            "chatbot_id": self.chatbot_id,
            "chat_id": self.chat_id,
            "rule_type": self.rule_type,
            "remark": self.remark,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
