"""
Forward Service 数据库访问层 (Repository/DAO)

提供对数据库的 CRUD 操作，封装所有数据库访问逻辑。
"""
import logging
from typing import Optional, List
from sqlalchemy import select, update, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Chatbot, ChatAccessRule
from .database import get_db_manager

logger = logging.getLogger(__name__)


# ============== Chatbot Repository ==============

class ChatbotRepository:
    """
    Chatbot 数据访问层

    提供对 chatbots 表的所有数据库操作
    """

    def __init__(self, session: AsyncSession):
        """
        初始化 Repository

        Args:
            session: SQLAlchemy AsyncSession
        """
        self.session = session

    async def create(
        self,
        bot_key: str,
        name: str,
        url_template: str,
        agent_id: str = "",
        api_key: str = "",
        timeout: int = 60,
        access_mode: str = "allow_all",
        description: str = "",
        enabled: bool = True
    ) -> Chatbot:
        """
        创建新的 Bot 配置

        Args:
            bot_key: Bot Key (唯一)
            name: Bot 名称
            url_template: 转发 URL 模板
            agent_id: Agent ID
            api_key: API Key
            timeout: 超时时间
            access_mode: 访问控制模式
            description: 描述
            enabled: 是否启用

        Returns:
            创建的 Chatbot 对象
        """
        bot = Chatbot(
            bot_key=bot_key,
            name=name,
            url_template=url_template,
            agent_id=agent_id,
            api_key=api_key,
            timeout=timeout,
            access_mode=access_mode,
            description=description,
            enabled=enabled
        )

        self.session.add(bot)
        await self.session.flush()

        logger.info(f"创建 Bot: {bot_key} ({name})")
        return bot

    async def get_by_id(self, bot_id: int) -> Optional[Chatbot]:
        """
        根据 ID 获取 Bot

        Args:
            bot_id: Bot ID

        Returns:
            Chatbot 对象或 None
        """
        stmt = select(Chatbot).where(Chatbot.id == bot_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_bot_key(self, bot_key: str) -> Optional[Chatbot]:
        """
        根据 bot_key 获取 Bot

        Args:
            bot_key: Bot Key

        Returns:
            Chatbot 对象或 None
        """
        stmt = select(Chatbot).where(Chatbot.bot_key == bot_key)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all(
        self,
        enabled_only: bool = False,
        include_rules: bool = False
    ) -> List[Chatbot]:
        """
        获取所有 Bot

        Args:
            enabled_only: 是否只返回启用的 Bot
            include_rules: 是否预加载访问规则

        Returns:
            Chatbot 对象列表
        """
        stmt = select(Chatbot)

        if enabled_only:
            stmt = stmt.where(Chatbot.enabled == True)

        # 按 ID 排序
        stmt = stmt.order_by(Chatbot.id)

        result = await self.session.execute(stmt)
        bots = result.scalars().all()

        return list(bots)

    async def update(
        self,
        bot_id: int,
        name: str | None = None,
        url_template: str | None = None,
        agent_id: str | None = None,
        api_key: str | None = None,
        timeout: int | None = None,
        access_mode: str | None = None,
        description: str | None = None,
        enabled: bool | None = None
    ) -> Optional[Chatbot]:
        """
        更新 Bot 配置

        Args:
            bot_id: Bot ID
            name: Bot 名称
            url_template: URL 模板
            agent_id: Agent ID
            api_key: API Key
            timeout: 超时时间
            access_mode: 访问控制模式
            description: 描述
            enabled: 是否启用

        Returns:
            更新后的 Chatbot 对象或 None
        """
        # 构建更新数据
        update_data = {}
        if name is not None:
            update_data["name"] = name
        if url_template is not None:
            update_data["url_template"] = url_template
        if agent_id is not None:
            update_data["agent_id"] = agent_id
        if api_key is not None:
            update_data["api_key"] = api_key
        if timeout is not None:
            update_data["timeout"] = timeout
        if access_mode is not None:
            update_data["access_mode"] = access_mode
        if description is not None:
            update_data["description"] = description
        if enabled is not None:
            update_data["enabled"] = enabled

        if not update_data:
            return await self.get_by_id(bot_id)

        # 执行更新
        stmt = (
            update(Chatbot)
            .where(Chatbot.id == bot_id)
            .values(**update_data)
        )
        await self.session.execute(stmt)
        await self.session.flush()

        logger.info(f"更新 Bot: id={bot_id}, fields={list(update_data.keys())}")
        return await self.get_by_id(bot_id)

    async def delete(self, bot_id: int) -> bool:
        """
        删除 Bot

        Args:
            bot_id: Bot ID

        Returns:
            是否删除成功
        """
        # 先检查是否存在
        bot = await self.get_by_id(bot_id)
        if not bot:
            return False

        # 执行删除 (会级联删除关联的 access_rules)
        stmt = delete(Chatbot).where(Chatbot.id == bot_id)
        await self.session.execute(stmt)
        await self.session.flush()

        logger.info(f"删除 Bot: id={bot_id}, bot_key={bot.bot_key}")
        return True

    async def count(self, enabled_only: bool = False) -> int:
        """
        统计 Bot 数量

        Args:
            enabled_only: 是否只统计启用的 Bot

        Returns:
            Bot 数量
        """
        stmt = select(func.count(Chatbot.id))
        if enabled_only:
            stmt = stmt.where(Chatbot.enabled == True)

        result = await self.session.execute(stmt)
        return result.scalar_one()


# ============== ChatAccessRule Repository ==============

class ChatAccessRuleRepository:
    """
    ChatAccessRule 数据访问层

    提供对 chat_access_rules 表的所有数据库操作
    """

    def __init__(self, session: AsyncSession):
        """
        初始化 Repository

        Args:
            session: SQLAlchemy AsyncSession
        """
        self.session = session

    async def create(
        self,
        chatbot_id: int,
        chat_id: str,
        rule_type: str,
        remark: str = ""
    ) -> ChatAccessRule:
        """
        创建访问规则

        Args:
            chatbot_id: Bot ID
            chat_id: Chat ID (用户ID或群ID)
            rule_type: 规则类型 (whitelist/blacklist)
            remark: 备注

        Returns:
            创建的 ChatAccessRule 对象
        """
        rule = ChatAccessRule(
            chatbot_id=chatbot_id,
            chat_id=chat_id,
            rule_type=rule_type,
            remark=remark
        )

        self.session.add(rule)
        await self.session.flush()

        logger.info(f"创建访问规则: chatbot_id={chatbot_id}, chat_id={chat_id}, type={rule_type}")
        return rule

    async def get_by_id(self, rule_id: int) -> Optional[ChatAccessRule]:
        """
        根据 ID 获取规则

        Args:
            rule_id: 规则 ID

        Returns:
            ChatAccessRule 对象或 None
        """
        stmt = select(ChatAccessRule).where(ChatAccessRule.id == rule_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_chatbot(
        self,
        chatbot_id: int,
        rule_type: str | None = None
    ) -> List[ChatAccessRule]:
        """
        获取 Bot 的所有访问规则

        Args:
            chatbot_id: Bot ID
            rule_type: 规则类型过滤 (whitelist/blacklist，None 表示全部)

        Returns:
            ChatAccessRule 对象列表
        """
        stmt = select(ChatAccessRule).where(ChatAccessRule.chatbot_id == chatbot_id)

        if rule_type:
            stmt = stmt.where(ChatAccessRule.rule_type == rule_type)

        stmt = stmt.order_by(ChatAccessRule.id)

        result = await self.session.execute(stmt)
        rules = result.scalars().all()

        return list(rules)

    async def get_whitelist(self, chatbot_id: int) -> List[str]:
        """
        获取 Bot 的白名单 Chat ID 列表

        Args:
            chatbot_id: Bot ID

        Returns:
            Chat ID 列表
        """
        stmt = select(ChatAccessRule.chat_id).where(
            ChatAccessRule.chatbot_id == chatbot_id,
            ChatAccessRule.rule_type == "whitelist"
        )

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_blacklist(self, chatbot_id: int) -> List[str]:
        """
        获取 Bot 的黑名单 Chat ID 列表

        Args:
            chatbot_id: Bot ID

        Returns:
            Chat ID 列表
        """
        stmt = select(ChatAccessRule.chat_id).where(
            ChatAccessRule.chatbot_id == chatbot_id,
            ChatAccessRule.rule_type == "blacklist"
        )

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def delete(self, rule_id: int) -> bool:
        """
        删除规则

        Args:
            rule_id: 规则 ID

        Returns:
            是否删除成功
        """
        rule = await self.get_by_id(rule_id)
        if not rule:
            return False

        stmt = delete(ChatAccessRule).where(ChatAccessRule.id == rule_id)
        await self.session.execute(stmt)
        await self.session.flush()

        logger.info(f"删除访问规则: id={rule_id}")
        return True

    async def delete_by_chatbot(self, chatbot_id: int) -> int:
        """
        删除 Bot 的所有访问规则

        Args:
            chatbot_id: Bot ID

        Returns:
            删除的规则数量
        """
        stmt = delete(ChatAccessRule).where(ChatAccessRule.chatbot_id == chatbot_id)
        result = await self.session.execute(stmt)
        await self.session.flush()

        count = result.rowcount
        logger.info(f"删除 Bot {chatbot_id} 的所有访问规则: count={count}")
        return count

    async def set_whitelist(
        self,
        chatbot_id: int,
        chat_ids: List[str],
        clear_existing: bool = True
    ) -> List[ChatAccessRule]:
        """
        设置白名单 (批量)

        Args:
            chatbot_id: Bot ID
            chat_ids: Chat ID 列表
            clear_existing: 是否清除现有白名单

        Returns:
            创建的规则列表
        """
        # 清除现有白名单
        if clear_existing:
            await self._clear_rules_by_type(chatbot_id, "whitelist")

        # 批量创建新规则
        rules = []
        for chat_id in chat_ids:
            rule = await self.create(chatbot_id, chat_id, "whitelist")
            rules.append(rule)

        logger.info(f"设置白名单: chatbot_id={chatbot_id}, count={len(rules)}")
        return rules

    async def set_blacklist(
        self,
        chatbot_id: int,
        chat_ids: List[str],
        clear_existing: bool = True
    ) -> List[ChatAccessRule]:
        """
        设置黑名单 (批量)

        Args:
            chatbot_id: Bot ID
            chat_ids: Chat ID 列表
            clear_existing: 是否清除现有黑名单

        Returns:
            创建的规则列表
        """
        # 清除现有黑名单
        if clear_existing:
            await self._clear_rules_by_type(chatbot_id, "blacklist")

        # 批量创建新规则
        rules = []
        for chat_id in chat_ids:
            rule = await self.create(chatbot_id, chat_id, "blacklist")
            rules.append(rule)

        logger.info(f"设置黑名单: chatbot_id={chatbot_id}, count={len(rules)}")
        return rules

    async def _clear_rules_by_type(self, chatbot_id: int, rule_type: str):
        """清除指定类型的所有规则"""
        stmt = delete(ChatAccessRule).where(
            ChatAccessRule.chatbot_id == chatbot_id,
            ChatAccessRule.rule_type == rule_type
        )
        await self.session.execute(stmt)
        await self.session.flush()


# ============== 辅助函数 ==============

def get_chatbot_repository(session: AsyncSession) -> ChatbotRepository:
    """获取 ChatbotRepository 实例"""
    return ChatbotRepository(session)


def get_access_rule_repository(session: AsyncSession) -> ChatAccessRuleRepository:
    """获取 ChatAccessRuleRepository 实例"""
    return ChatAccessRuleRepository(session)
