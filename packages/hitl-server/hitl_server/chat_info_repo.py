"""
Chat Info Repository

用于查询和记录 chat_id 到 chat_type 的映射
"""
import logging
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ChatInfo

logger = logging.getLogger(__name__)


class ChatInfoRepository:
    """
    Chat Info 数据访问层
    
    提供对 chat_info 表的所有数据库操作
    """
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def get_by_chat_id(self, chat_id: str) -> Optional[ChatInfo]:
        """
        根据 chat_id 获取 Chat 信息
        
        Args:
            chat_id: Chat ID
        
        Returns:
            ChatInfo 对象，如果不存在则返回 None
        """
        result = await self.session.execute(
            select(ChatInfo).where(ChatInfo.chat_id == chat_id)
        )
        return result.scalar_one_or_none()
    
    async def record_chat(
        self,
        chat_id: str,
        chat_type: str,
        chat_name: Optional[str] = None,
        bot_key: Optional[str] = None
    ) -> ChatInfo:
        """
        记录或更新 Chat 信息
        
        如果 chat_id 已存在，更新 last_seen_at 和 message_count
        如果 chat_id 不存在，创建新记录
        
        Args:
            chat_id: Chat ID
            chat_type: Chat 类型 ("group" / "single")
            chat_name: Chat 名称（可选）
            bot_key: 收到消息的 Bot Key（可选）
        
        Returns:
            ChatInfo 对象
        """
        existing = await self.get_by_chat_id(chat_id)
        
        if existing:
            # 更新现有记录
            existing.message_count += 1
            existing.last_seen_at = datetime.now(timezone.utc)
            # 如果 chat_type 发生变化（理论上不应该），记录日志
            if existing.chat_type != chat_type:
                logger.warning(
                    f"Chat {chat_id} 的 chat_type 发生变化: {existing.chat_type} -> {chat_type}"
                )
                existing.chat_type = chat_type
            await self.session.flush()
            return existing
        else:
            # 创建新记录
            chat_info = ChatInfo(
                chat_id=chat_id,
                chat_type=chat_type,
                chat_name=chat_name,
                first_bot_key=bot_key,
                message_count=1,
                first_seen_at=datetime.now(timezone.utc),
                last_seen_at=datetime.now(timezone.utc)
            )
            self.session.add(chat_info)
            await self.session.flush()
            logger.info(f"记录新 Chat: chat_id={chat_id}, chat_type={chat_type}")
            return chat_info


def get_chat_info_repository(session: AsyncSession) -> ChatInfoRepository:
    """获取 ChatInfoRepository 实例"""
    return ChatInfoRepository(session)
