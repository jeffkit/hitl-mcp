"""
HIL Server Slash 命令处理

支持的命令：
- /waiting 或 /w - 查看等待回复的消息
- /reply <id> <内容> - 回复指定消息
- /status - 服务状态（管理员）
- /sessions - 所有会话列表（管理员）
- /ping - 健康检查
- /help - 帮助信息
"""
import re
import logging
from datetime import datetime
from typing import Optional

from ..storage import storage
from ..config import config

logger = logging.getLogger(__name__)


# ============== Slash 命令正则 ==============

SLASH_COMMANDS = {
    "waiting": re.compile(r'^/(?:waiting|w)\s*$', re.IGNORECASE),
    "reply": re.compile(r'^/(?:reply|r)\s+([a-f0-9]{6,8})\s+(.+)', re.IGNORECASE | re.DOTALL),
    "quick_reply": re.compile(r'^/([1-9])\s+(.+)', re.IGNORECASE | re.DOTALL),  # /1 内容, /2 内容 快捷回复
    "status": re.compile(r'^/status\s*$', re.IGNORECASE),
    "sessions": re.compile(r'^/sessions?\s*$', re.IGNORECASE),
    "ping": re.compile(r'^/ping\s*$', re.IGNORECASE),
    "help": re.compile(r'^/help\s*$', re.IGNORECASE),
}

# 临时缓存：用于 /1, /2 等快捷回复
# key: chat_id, value: list[session_id]（最近 /w 命令显示的会话列表）
_waiting_sessions_cache: dict[str, list[str]] = {}


# ============== 命令解析 ==============

def parse_slash_command(message: str) -> Optional[tuple[str, Optional[str], Optional[str]]]:
    """
    解析 Slash 命令
    
    Returns:
        (command_type, arg1, arg2) 或 None
        - waiting: ("waiting", None, None)
        - reply: ("reply", short_id, content)
        - quick_reply: ("quick_reply", index, content)
        - status: ("status", None, None)
        - sessions: ("sessions", None, None)
        - ping: ("ping", None, None)
        - help: ("help", None, None)
    """
    message = message.strip()
    
    for cmd_type, pattern in SLASH_COMMANDS.items():
        match = pattern.match(message)
        if match:
            if cmd_type == "reply":
                # reply 命令有两个参数
                return (cmd_type, match.group(1), match.group(2))
            elif cmd_type == "quick_reply":
                # quick_reply: /1 内容, /2 内容
                return (cmd_type, match.group(1), match.group(2))
            return (cmd_type, None, None)
    
    return None


# ============== 管理员检查 ==============

async def is_admin(user_id: str, user_alias: str = "") -> bool:
    """
    检查用户是否是管理员
    
    管理员配置存储在数据库的 SystemConfig 表中
    """
    # 简化实现：检查配置的管理员用户名
    admin_username = config.admin_username
    return user_alias == admin_username or user_id == admin_username


# ============== 命令处理 ==============

async def handle_waiting(chat_id: str, user_id: str) -> str:
    """
    处理 /waiting 命令 - 查看等待回复的消息
    """
    sessions = await storage.get_waiting_sessions_by_chat_id(chat_id)
    
    if not sessions:
        _waiting_sessions_cache.pop(chat_id, None)
        return "📭 当前没有等待你回复的消息"
    
    # 缓存会话列表，用于 /1, /2 等快捷回复
    _waiting_sessions_cache[chat_id] = [s.session_id for s in sessions]
    
    lines = ["📋 **等待回复的消息**\n"]
    
    for i, session in enumerate(sessions, 1):
        # 计算等待时间
        elapsed = datetime.now() - session.created_at
        minutes = int(elapsed.total_seconds() / 60)
        if minutes < 1:
            time_str = "刚刚"
        elif minutes < 60:
            time_str = f"{minutes}分钟"
        else:
            hours = minutes // 60
            time_str = f"{hours}小时"
        
        # 截断消息预览
        preview = session.message[:35] + "..." if len(session.message) > 35 else session.message
        project_tag = f" [{session.project_name}]" if session.project_name else ""
        
        lines.append(f"**{i}.** ⏳{project_tag} `{session.short_id}`")
        lines.append(f"   {preview}")
        lines.append(f"   等待 {time_str}")
    
    lines.append("\n---")
    if len(sessions) == 1:
        lines.append("💡 回复: `/1 <内容>` 或 `/r {0} <内容>`".format(sessions[0].short_id))
    else:
        lines.append("💡 回复: `/1 <内容>`, `/2 <内容>` 或 `/r <短ID> <内容>`")
    
    return "\n".join(lines)


async def handle_reply(chat_id: str, user_id: str, short_id: str, content: str, from_user: dict) -> str:
    """
    处理 /reply 命令 - 回复指定消息
    """
    # 根据 short_id 查找会话
    session = await storage.get_session_by_short_id(short_id, chat_id)
    
    if not session:
        return f"❌ 未找到会话 `{short_id}`\n使用 `/w` 查看等待回复的会话"
    
    if session.status != "waiting":
        return f"❌ 会话 `{short_id}` 已结束，状态: {session.status}"
    
    # 添加回复
    reply_data = {
        "msg_type": "text",
        "content": content,
        "from_user": from_user,
        "timestamp": datetime.now().isoformat()
    }
    
    success = await storage.add_reply(session.session_id, reply_data)
    
    if success:
        return f"✅ 已回复会话 `{short_id}`"
    else:
        return f"❌ 回复失败，请重试"


async def handle_quick_reply(chat_id: str, user_id: str, index: str, content: str, from_user: dict) -> str:
    """
    处理 /1, /2 等快捷回复命令
    """
    idx = int(index) - 1  # 转为 0-based 索引
    
    # 检查缓存
    cached_sessions = _waiting_sessions_cache.get(chat_id, [])
    
    if not cached_sessions:
        return "❌ 请先使用 `/w` 查看等待回复的消息"
    
    if idx < 0 or idx >= len(cached_sessions):
        return f"❌ 无效的序号 {index}，当前有 {len(cached_sessions)} 个等待中的会话"
    
    session_id = cached_sessions[idx]
    session = await storage.get_session(session_id)
    
    if not session:
        return f"❌ 会话已过期，请使用 `/w` 刷新列表"
    
    if session.status != "waiting":
        return f"❌ 会话已结束，状态: {session.status}"
    
    # 添加回复
    reply_data = {
        "msg_type": "text",
        "content": content,
        "from_user": from_user,
        "timestamp": datetime.now().isoformat()
    }
    
    success = await storage.add_reply(session.session_id, reply_data)
    
    if success:
        # 从缓存中移除已回复的会话
        cached_sessions.pop(idx)
        return f"✅ 已回复第 {index} 个会话"
    else:
        return f"❌ 回复失败，请重试"


async def handle_status(user_id: str, user_alias: str) -> str:
    """
    处理 /status 命令 - 服务状态（管理员）
    """
    if not await is_admin(user_id, user_alias):
        return "⚠️ 此命令仅限管理员使用"
    
    stats = await storage.get_session_stats()
    
    mode = config.effective_mode
    uptime = "N/A"  # 可以添加启动时间追踪
    
    lines = [
        "📊 **HIL Server 状态**\n",
        f"• 运行模式: {mode}",
        f"• 等待中会话: {stats.get('waiting', 0)}",
        f"• 已回复会话: {stats.get('replied', 0)}",
        f"• 已超时会话: {stats.get('timeout', 0)}",
        f"• 总会话数: {stats.get('total', 0)}",
    ]
    
    if mode == "relay":
        from ..ws_manager import ws_manager
        worker_count = len(ws_manager._workers)
        lines.append(f"• Worker 连接数: {worker_count}")
    
    return "\n".join(lines)


async def handle_sessions(chat_id: str, user_id: str, user_alias: str) -> str:
    """
    处理 /sessions 命令 - 所有会话列表（管理员）
    """
    if not await is_admin(user_id, user_alias):
        return "⚠️ 此命令仅限管理员使用"
    
    sessions = await storage.get_all_sessions(limit=20)
    
    if not sessions:
        return "📭 暂无会话记录"
    
    lines = ["📋 **最近会话（最多20条）**\n"]
    
    for session in sessions:
        status_icon = {
            "waiting": "⏳",
            "replied": "✅",
            "timeout": "⏰",
            "expired": "❌"
        }.get(session.get("status", ""), "❓")
        
        short_id = session.get("short_id", "")
        project = session.get("project_name", "")
        preview = session.get("message", "")[:30] + "..." if len(session.get("message", "")) > 30 else session.get("message", "")
        
        lines.append(f"{status_icon} `{short_id}` {project}: {preview}")
    
    return "\n".join(lines)


async def handle_ping() -> str:
    """
    处理 /ping 命令 - 健康检查
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"🏓 Pong!\n服务正常运行\n⏰ {now}"


async def handle_help(user_id: str, user_alias: str) -> str:
    """
    处理 /help 命令 - 帮助信息
    """
    lines = [
        "📖 **HIL Server 命令帮助**\n",
        "**用户命令**",
        "• `/w` - 查看等待回复的消息",
        "• `/1 <内容>` - 快捷回复第1个消息",
        "• `/2 <内容>` - 快捷回复第2个消息",
        "• `/r <短ID> <内容>` - 按ID回复消息",
        "• `/ping` - 健康检查",
        "• `/help` - 显示此帮助",
    ]
    
    if await is_admin(user_id, user_alias):
        lines.extend([
            "\n**管理员命令**",
            "• `/status` - 服务状态",
            "• `/sessions` - 所有会话列表",
        ])
    
    return "\n".join(lines)


# ============== 主处理函数 ==============

async def process_slash_command(
    command: str,
    chat_id: str,
    user_id: str,
    user_alias: str,
    from_user: dict
) -> Optional[str]:
    """
    处理 Slash 命令
    
    Args:
        command: 用户输入的命令
        chat_id: 会话 ID
        user_id: 用户 ID
        user_alias: 用户别名
        from_user: 用户信息字典
    
    Returns:
        响应消息，如果不是 slash 命令则返回 None
    """
    parsed = parse_slash_command(command)
    
    if not parsed:
        return None
    
    cmd_type, arg1, arg2 = parsed
    logger.info(f"处理 HIL Slash 命令: {cmd_type}, user={user_alias or user_id}")
    
    if cmd_type == "waiting":
        return await handle_waiting(chat_id, user_id)
    
    elif cmd_type == "reply":
        return await handle_reply(chat_id, user_id, arg1, arg2, from_user)
    
    elif cmd_type == "quick_reply":
        return await handle_quick_reply(chat_id, user_id, arg1, arg2, from_user)
    
    elif cmd_type == "status":
        return await handle_status(user_id, user_alias)
    
    elif cmd_type == "sessions":
        return await handle_sessions(chat_id, user_id, user_alias)
    
    elif cmd_type == "ping":
        return await handle_ping()
    
    elif cmd_type == "help":
        return await handle_help(user_id, user_alias)
    
    return None
