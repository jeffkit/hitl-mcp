"""
Forward Service 会话管理器

管理用户与 Agent 的会话：
- 记录 session_id
- 支持会话持续性
- 处理 Slash 命令
"""
import logging
import re
from datetime import datetime
from typing import Optional

from sqlalchemy import select, update, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from .models import UserSession

logger = logging.getLogger(__name__)

# Slash 命令正则
SLASH_COMMANDS = {
    "list": re.compile(r'^/(sess|s)\s*$', re.IGNORECASE),
    "reset": re.compile(r'^/(reset|r)\s*$', re.IGNORECASE),
    # 允许会话 ID 后面有空格和消息内容
    "change": re.compile(r'^/(change|c)\s+([a-f0-9]{6,8})(?:\s+(.+))?$', re.IGNORECASE | re.DOTALL),
}


class SessionManager:
    """会话管理器"""
    
    def __init__(self, db_manager):
        self._db_manager = db_manager
    
    async def get_active_session(
        self,
        user_id: str,
        chat_id: str,
        bot_key: str
    ) -> Optional[UserSession]:
        """
        获取用户的活跃会话
        
        Returns:
            活跃的 UserSession，如果没有返回 None
        """
        async with self._db_manager.get_session() as db:
            result = await db.execute(
                select(UserSession)
                .where(and_(
                    UserSession.user_id == user_id,
                    UserSession.chat_id == chat_id,
                    UserSession.bot_key == bot_key,
                    UserSession.is_active == True
                ))
                .order_by(desc(UserSession.updated_at))
                .limit(1)
            )
            return result.scalar_one_or_none()
    
    async def record_session(
        self,
        user_id: str,
        chat_id: str,
        bot_key: str,
        session_id: str,
        last_message: str
    ) -> UserSession:
        """
        记录或更新会话
        
        如果是新的 session_id，创建新会话并将旧会话设为非活跃
        如果是相同的 session_id，更新最后消息
        """
        short_id = session_id[:8] if len(session_id) >= 8 else session_id
        truncated_message = last_message[:200] if last_message else ""
        
        async with self._db_manager.get_session() as db:
            # 查找是否已存在该 session
            result = await db.execute(
                select(UserSession)
                .where(and_(
                    UserSession.user_id == user_id,
                    UserSession.chat_id == chat_id,
                    UserSession.bot_key == bot_key,
                    UserSession.session_id == session_id
                ))
            )
            existing = result.scalar_one_or_none()
            
            if existing:
                # 更新现有会话
                existing.last_message = truncated_message
                existing.message_count += 1
                existing.is_active = True
                existing.updated_at = datetime.utcnow()
                await db.commit()
                return existing
            else:
                # 将该用户的其他会话设为非活跃
                await db.execute(
                    update(UserSession)
                    .where(and_(
                        UserSession.user_id == user_id,
                        UserSession.chat_id == chat_id,
                        UserSession.bot_key == bot_key,
                        UserSession.is_active == True
                    ))
                    .values(is_active=False)
                )
                
                # 创建新会话
                new_session = UserSession(
                    user_id=user_id,
                    chat_id=chat_id,
                    bot_key=bot_key,
                    session_id=session_id,
                    short_id=short_id,
                    last_message=truncated_message,
                    message_count=1,
                    is_active=True
                )
                db.add(new_session)
                await db.commit()
                await db.refresh(new_session)
                
                logger.info(f"新会话创建: user={user_id[:10]}, session={short_id}")
                return new_session
    
    async def list_sessions(
        self,
        user_id: str,
        chat_id: str,
        limit: int = 10
    ) -> list[UserSession]:
        """
        列出用户最近的会话
        """
        async with self._db_manager.get_session() as db:
            result = await db.execute(
                select(UserSession)
                .where(and_(
                    UserSession.user_id == user_id,
                    UserSession.chat_id == chat_id
                ))
                .order_by(desc(UserSession.updated_at))
                .limit(limit)
            )
            return list(result.scalars().all())
    
    async def reset_session(
        self,
        user_id: str,
        chat_id: str,
        bot_key: str
    ) -> bool:
        """
        重置会话（将当前会话设为非活跃）
        
        Returns:
            是否成功重置
        """
        async with self._db_manager.get_session() as db:
            result = await db.execute(
                update(UserSession)
                .where(and_(
                    UserSession.user_id == user_id,
                    UserSession.chat_id == chat_id,
                    UserSession.bot_key == bot_key,
                    UserSession.is_active == True
                ))
                .values(is_active=False)
            )
            await db.commit()
            
            if result.rowcount > 0:
                logger.info(f"会话已重置: user={user_id[:10]}, chat={chat_id[:10]}")
                return True
            return False
    
    async def change_session(
        self,
        user_id: str,
        chat_id: str,
        short_id: str
    ) -> Optional[UserSession]:
        """
        切换到指定会话
        
        Returns:
            切换到的 UserSession，如果没找到返回 None
        """
        async with self._db_manager.get_session() as db:
            # 查找目标会话（使用 like 进行前缀匹配）
            # 先尝试精确匹配 short_id
            result = await db.execute(
                select(UserSession)
                .where(and_(
                    UserSession.user_id == user_id,
                    UserSession.chat_id == chat_id,
                    UserSession.short_id == short_id
                ))
            )
            target = result.scalar_one_or_none()
            
            # 如果精确匹配没找到，尝试用 session_id 前缀匹配
            if not target:
                result = await db.execute(
                    select(UserSession)
                    .where(and_(
                        UserSession.user_id == user_id,
                        UserSession.chat_id == chat_id,
                        UserSession.session_id.like(f"{short_id}%")
                    ))
                )
                target = result.scalar_one_or_none()
            
            if not target:
                return None
            
            # 将其他会话设为非活跃
            await db.execute(
                update(UserSession)
                .where(and_(
                    UserSession.user_id == user_id,
                    UserSession.chat_id == chat_id,
                    UserSession.is_active == True,
                    UserSession.id != target.id
                ))
                .values(is_active=False)
            )
            
            # 激活目标会话
            target.is_active = True
            target.updated_at = datetime.utcnow()
            await db.commit()
            
            logger.info(f"会话已切换: user={user_id[:10]}, session={target.short_id}")
            return target
    
    def parse_slash_command(self, message: str) -> Optional[tuple[str, Optional[str], Optional[str]]]:
        """
        解析 Slash 命令
        
        Returns:
            (command_type, arg, extra_message) 或 None
            command_type: "list", "reset", "change"
            arg: 命令参数（如 short_id）
            extra_message: 附带消息（仅 /c 命令支持，如 "/c abc123 你好" 中的 "你好"）
        """
        message = message.strip()
        
        for cmd_type, pattern in SLASH_COMMANDS.items():
            match = pattern.match(message)
            if match:
                if cmd_type == "change":
                    # change 命令特殊处理：group(2) 是 short_id, group(3) 是附带消息
                    short_id = match.group(2)
                    extra_msg = match.group(3).strip() if match.lastindex >= 3 and match.group(3) else None
                    return (cmd_type, short_id, extra_msg)
                else:
                    arg = match.group(2) if match.lastindex and match.lastindex >= 2 else None
                    return (cmd_type, arg, None)
        
        return None
    
    def format_session_list(self, sessions: list[UserSession]) -> str:
        """
        格式化会话列表为用户可读的消息
        """
        if not sessions:
            return "📭 暂无会话记录"
        
        lines = ["📋 **最近会话**\n"]
        
        for i, s in enumerate(sessions, 1):
            active_mark = "✅" if s.is_active else "  "
            preview = (s.last_message[:30] + "...") if s.last_message and len(s.last_message) > 30 else (s.last_message or "")
            lines.append(f"{active_mark} `{s.short_id}` - {preview} ({s.message_count}条)")
        
        lines.append("\n---")
        lines.append("💡 命令: `/c <短ID>` 切换会话, `/r` 新建会话")
        
        return "\n".join(lines)


# 全局会话管理器实例（延迟初始化）
_session_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    """获取全局会话管理器"""
    global _session_manager
    if _session_manager is None:
        raise RuntimeError("SessionManager 未初始化")
    return _session_manager


def init_session_manager(db_manager) -> SessionManager:
    """初始化全局会话管理器"""
    global _session_manager
    _session_manager = SessionManager(db_manager)
    logger.info("SessionManager 已初始化")
    return _session_manager
