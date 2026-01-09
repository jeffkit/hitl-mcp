"""
回调处理路由

处理企微机器人回调
"""
import json
import logging
from datetime import datetime

from fastapi import APIRouter, Request, Header

from ..config import config
from ..sender import send_reply
from ..session_manager import get_session_manager
from ..database import get_db_manager
from ..repository import get_system_config_repository, get_forward_log_repository
from ..utils import extract_content
from ..services import forward_to_agent_with_bot
from .admin import add_request_log, update_request_log, RequestLogData

logger = logging.getLogger(__name__)


# ============== 管理员权限检查 ==============

async def check_is_admin(user_id: str, alias: str = None) -> bool:
    """
    检查用户是否是管理员
    
    管理员列表存储在 system_config 表的 admin_users 键中
    格式: JSON 数组 ["user_id_1", "alias_1", ...]
    """
    try:
        db_manager = get_db_manager()
        async with db_manager.get_session() as session:
            repo = get_system_config_repository(session)
            admin_users_json = await repo.get_value("admin_users", "[]")
            admin_users = json.loads(admin_users_json)
            
            # 检查 user_id 或 alias 是否在管理员列表中
            if user_id in admin_users:
                return True
            if alias and alias in admin_users:
                return True
            
            return False
    except Exception as e:
        logger.error(f"检查管理员权限失败: {e}")
        return False


async def get_system_status() -> str:
    """获取系统状态信息"""
    import sys
    from datetime import timedelta
    
    try:
        db_manager = get_db_manager()
        async with db_manager.get_session() as session:
            log_repo = get_forward_log_repository(session)
            
            # 获取统计数据
            total_count = await log_repo.count()
            
            # 获取今日统计
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            from sqlalchemy import select, func
            from ..models import ForwardLog
            
            today_stmt = (
                select(func.count(ForwardLog.id))
                .where(ForwardLog.timestamp >= today_start)
            )
            today_result = await session.execute(today_stmt)
            today_count = today_result.scalar() or 0
            
            # 今日成功数
            success_stmt = (
                select(func.count(ForwardLog.id))
                .where(ForwardLog.timestamp >= today_start)
                .where(ForwardLog.status == "success")
            )
            success_result = await session.execute(success_stmt)
            success_count = success_result.scalar() or 0
            
            # 平均响应时间
            avg_stmt = (
                select(func.avg(ForwardLog.duration_ms))
                .where(ForwardLog.timestamp >= today_start)
                .where(ForwardLog.status == "success")
            )
            avg_result = await session.execute(avg_stmt)
            avg_duration = avg_result.scalar() or 0
        
        # 计算成功率
        success_rate = (success_count / today_count * 100) if today_count > 0 else 100
        
        # 格式化响应时间
        if avg_duration > 1000:
            avg_duration_str = f"{avg_duration/1000:.1f}s"
        else:
            avg_duration_str = f"{int(avg_duration)}ms"
        
        return f"""🟢 Forward Service 状态

📊 版本: 3.0.0
🤖 Bot 数量: {len(config.bots)} 个

📈 今日统计
• 消息数: {today_count} 条
• 成功率: {success_rate:.1f}%
• 平均响应: {avg_duration_str}

📚 历史总消息: {total_count} 条"""
    
    except Exception as e:
        logger.error(f"获取系统状态失败: {e}")
        return f"⚠️ 获取系统状态失败: {e}"


# ============== 进行中请求追踪 ==============

# 存储正在处理的请求 {request_id: {bot_name, user, message, start_time}}
_pending_requests: dict[str, dict] = {}


def add_pending_request(request_id: str, bot_name: str, user: str, message: str):
    """添加进行中的请求"""
    _pending_requests[request_id] = {
        "bot_name": bot_name,
        "user": user,
        "message": message[:50],
        "start_time": datetime.now()
    }


def remove_pending_request(request_id: str):
    """移除已完成的请求"""
    _pending_requests.pop(request_id, None)


def get_pending_requests() -> list[dict]:
    """获取所有进行中的请求"""
    result = []
    now = datetime.now()
    for req_id, req in _pending_requests.items():
        elapsed = (now - req["start_time"]).total_seconds()
        result.append({
            **req,
            "elapsed_seconds": elapsed,
            "elapsed_str": f"{int(elapsed // 60)}分{int(elapsed % 60)}秒"
        })
    return sorted(result, key=lambda x: x["elapsed_seconds"], reverse=True)


# ============== 管理命令处理 ==============

async def get_admin_help() -> str:
    """生成管理员帮助信息"""
    return """📖 管理员命令帮助

🔧 系统状态
• /ping - 健康检查
• /status - 系统状态

🤖 Bot 管理
• /bots - 列出所有 Bot
• /bot <name> - 查看 Bot 详情

📊 请求监控
• /pending - 正在处理的请求
• /recent - 最近 10 条日志
• /errors - 最近错误

🏥 运维
• /health - 检查 Agent 可达性

💬 会话管理（所有用户可用）
• /s - 列出会话
• /r - 重置会话
• /c <id> - 切换会话"""


async def get_bots_list() -> str:
    """获取所有 Bot 列表"""
    bots = config.bots
    if not bots:
        return "📭 暂无配置的 Bot"
    
    lines = ["🤖 Bot 列表\n"]
    for bot in bots:
        status = "✅" if bot.enabled else "❌"
        lines.append(f"{status} {bot.name}")
    
    return "\n".join(lines)


async def get_bot_detail(bot_name: str) -> str:
    """获取 Bot 详情"""
    from sqlalchemy import select, func
    from ..models import ForwardLog
    
    # 查找 Bot
    bot = None
    for b in config.bots:
        if b.name.lower() == bot_name.lower():
            bot = b
            break
    
    if not bot:
        return f"❌ 未找到 Bot: {bot_name}"
    
    try:
        db_manager = get_db_manager()
        async with db_manager.get_session() as session:
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            
            # 今日请求数
            today_stmt = (
                select(func.count(ForwardLog.id))
                .where(ForwardLog.bot_key == bot.bot_key)
                .where(ForwardLog.timestamp >= today_start)
            )
            today_result = await session.execute(today_stmt)
            today_count = today_result.scalar() or 0
            
            # 成功数
            success_stmt = (
                select(func.count(ForwardLog.id))
                .where(ForwardLog.bot_key == bot.bot_key)
                .where(ForwardLog.timestamp >= today_start)
                .where(ForwardLog.status == "success")
            )
            success_result = await session.execute(success_stmt)
            success_count = success_result.scalar() or 0
            
            # 平均响应时间
            avg_stmt = (
                select(func.avg(ForwardLog.duration_ms))
                .where(ForwardLog.bot_key == bot.bot_key)
                .where(ForwardLog.timestamp >= today_start)
                .where(ForwardLog.status == "success")
            )
            avg_result = await session.execute(avg_stmt)
            avg_duration = avg_result.scalar() or 0
            
            # 最近错误
            error_stmt = (
                select(ForwardLog.error, ForwardLog.timestamp)
                .where(ForwardLog.bot_key == bot.bot_key)
                .where(ForwardLog.status != "success")
                .order_by(ForwardLog.timestamp.desc())
                .limit(1)
            )
            error_result = await session.execute(error_stmt)
            last_error = error_result.first()
        
        success_rate = (success_count / today_count * 100) if today_count > 0 else 100
        avg_str = f"{avg_duration/1000:.1f}s" if avg_duration > 1000 else f"{int(avg_duration)}ms"
        error_info = last_error[0][:50] if last_error else "无"
        
        return f"""🤖 {bot.name} 状态

• 今日请求: {today_count} 条
• 成功率: {success_rate:.1f}%
• 平均响应: {avg_str}
• 最近错误: {error_info}
• 状态: {"启用" if bot.enabled else "禁用"}"""
    
    except Exception as e:
        return f"⚠️ 获取 Bot 详情失败: {e}"


async def get_pending_list() -> str:
    """获取正在处理的请求"""
    pending = get_pending_requests()
    
    if not pending:
        return "✅ 当前没有正在处理的请求"
    
    lines = [f"⏳ 正在处理的请求 ({len(pending)} 个)\n"]
    for i, req in enumerate(pending, 1):
        lines.append(f"{i}. {req['bot_name']}")
        lines.append(f"   用户: {req['user']}")
        lines.append(f"   消息: {req['message']}")
        lines.append(f"   等待: {req['elapsed_str']}")
        lines.append("")
    
    return "\n".join(lines)


async def get_recent_logs(limit: int = 10) -> str:
    """获取最近日志"""
    try:
        db_manager = get_db_manager()
        async with db_manager.get_session() as session:
            repo = get_forward_log_repository(session)
            logs = await repo.get_recent(limit)
        
        if not logs:
            return "📭 暂无日志记录"
        
        lines = [f"📋 最近 {len(logs)} 条日志\n"]
        for log in logs:
            status_icon = "✅" if log.status == "success" else "❌"
            time_str = log.timestamp.strftime("%H:%M:%S") if log.timestamp else "?"
            content = (log.content or "")[:20]
            lines.append(f"{status_icon} [{time_str}] {log.bot_name}: {content}")
        
        return "\n".join(lines)
    
    except Exception as e:
        return f"⚠️ 获取日志失败: {e}"


async def get_error_logs(limit: int = 5) -> str:
    """获取错误日志"""
    from sqlalchemy import select
    from ..models import ForwardLog
    
    try:
        db_manager = get_db_manager()
        async with db_manager.get_session() as session:
            stmt = (
                select(ForwardLog)
                .where(ForwardLog.status != "success")
                .order_by(ForwardLog.timestamp.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            logs = result.scalars().all()
        
        if not logs:
            return "✅ 暂无错误记录"
        
        lines = [f"❌ 最近 {len(logs)} 条错误\n"]
        for log in logs:
            time_str = log.timestamp.strftime("%m-%d %H:%M") if log.timestamp else "?"
            error = (log.error or log.status or "未知错误")[:40]
            lines.append(f"• [{time_str}] {log.bot_name}")
            lines.append(f"  {error}")
            lines.append("")
        
        return "\n".join(lines)
    
    except Exception as e:
        return f"⚠️ 获取错误日志失败: {e}"


async def check_agents_health() -> str:
    """检查所有 Agent 的健康状态"""
    import httpx
    
    bots = config.bots
    if not bots:
        return "📭 暂无配置的 Bot"
    
    lines = ["🏥 Agent 健康检查\n"]
    
    async with httpx.AsyncClient(timeout=5.0) as client:
        for bot in bots:
            url = bot.forward_config.get_url()
            # 只检查到域名/IP部分
            try:
                # 尝试 HEAD 请求到根路径
                base_url = "/".join(url.split("/")[:3])  # http://host:port
                response = await client.head(base_url, follow_redirects=True)
                status = "✅ 可达" if response.status_code < 500 else f"⚠️ {response.status_code}"
            except httpx.ConnectError:
                status = "❌ 连接失败"
            except httpx.TimeoutException:
                status = "⏱️ 超时"
            except Exception as e:
                status = f"❌ {str(e)[:20]}"
            
            lines.append(f"• {bot.name}: {status}")
    
    return "\n".join(lines)


router = APIRouter(tags=["callback"])


@router.post("/callback")
async def handle_callback(
    request: Request,
    x_api_key: str | None = Header(None, alias="x-api-key")
):
    """
    处理企微机器人回调（多 Bot 支持）
    
    工作流程：
    1. 从 webhook_url 提取 bot_key
    2. 查找对应的 Bot 配置
    3. 检查访问权限
    4. 转发到 Agent
    5. 将结果发送给用户
    """
    # 验证鉴权（可选）
    if config.callback_auth_key and config.callback_auth_value:
        if x_api_key != config.callback_auth_value:
            logger.warning(f"回调鉴权失败: x_api_key={x_api_key}")
            return {"errcode": 401, "errmsg": "Unauthorized"}
    
    start_time = datetime.now()
    log_id = None  # 日志 ID，用于更新响应信息
    
    try:
        data = await request.json()
        
        chat_id = data.get("chatid", "")
        chat_type = data.get("chattype", "group")
        msg_type = data.get("msgtype", "")
        from_user = data.get("from", {})
        from_user_name = from_user.get("name", "unknown")
        from_user_id = from_user.get("userid", "unknown")
        from_user_alias = from_user.get("alias", "")  # 用户别名
        webhook_url = data.get("webhook_url", "")
        
        logger.info(f"收到企微回调: chat_id={chat_id}, msg_type={msg_type}, from={from_user_name}")
        
        # 忽略某些事件类型
        if msg_type in ("event", "enter_chat"):
            logger.info(f"忽略事件类型: {msg_type}")
            return {"errcode": 0, "errmsg": "ok"}
        
        # === 多 Bot 支持：从 webhook_url 提取 bot_key ===
        bot_key = config.extract_bot_key_from_webhook_url(webhook_url)
        logger.info(f"提取的 bot_key: {bot_key}")
        
        # 获取 Bot 配置（如果找不到会回退到 default_bot）
        bot = config.get_bot_or_default(bot_key)
        if not bot:
            logger.warning(f"未找到 bot_key={bot_key} 的配置，且无默认 Bot")
            await send_reply(
                chat_id=chat_id,
                message="⚠️ Bot 配置错误，请联系管理员",
                msg_type="text"
            )
            return {"errcode": 0, "errmsg": "no bot config"}
        
        logger.info(f"使用 Bot: {bot.name} (key={bot.bot_key[:10]}...)")
        
        # === 访问控制检查 (同时检查 user_id, chat_id 和 alias) ===
        allowed, reason = config.check_access(bot, from_user_id, chat_id, from_user_alias)
        if not allowed:
            logger.warning(f"用户 {from_user_name} ({from_user_id}) 被拒绝访问 Bot {bot.name}: {reason}")
            
            # 尝试回退到默认 Bot
            if bot.bot_key != config.default_bot_key:
                logger.info(f"尝试回退到默认 Bot: {config.default_bot_key}")
                default_bot = config.get_bot(config.default_bot_key)
                if default_bot:
                    default_allowed, default_reason = config.check_access(default_bot, from_user_id, chat_id, from_user_alias)
                    if default_allowed:
                        bot = default_bot
                        logger.info(f"使用默认 Bot: {bot.name}")
                    else:
                        await send_reply(
                            chat_id=chat_id,
                            message=f"⚠️ {reason}\n\n默认 Bot 也无法访问: {default_reason}",
                            msg_type="text",
                            bot_key=default_bot.bot_key
                        )
                        return {"errcode": 0, "errmsg": "access denied"}
                else:
                    await send_reply(
                        chat_id=chat_id,
                        message=f"⚠️ {reason}",
                        msg_type="text",
                        bot_key=bot.bot_key
                    )
                    return {"errcode": 0, "errmsg": "access denied"}
            else:
                await send_reply(
                    chat_id=chat_id,
                    message=f"⚠️ {reason}",
                    msg_type="text",
                    bot_key=bot.bot_key
                )
                return {"errcode": 0, "errmsg": "access denied"}
        
        # 提取消息内容
        content, image_url = extract_content(data)
        
        if not content and not image_url:
            logger.warning("消息内容为空，跳过处理")
            return {"errcode": 0, "errmsg": "empty content"}
        
        # === 会话管理：处理 Slash 命令 ===
        if content:
            session_mgr = get_session_manager()
            slash_cmd = session_mgr.parse_slash_command(content)
            
            if slash_cmd:
                cmd_type, cmd_arg, extra_msg = slash_cmd
                logger.info(f"处理 Slash 命令: {cmd_type}, arg={cmd_arg}, extra={extra_msg[:20] if extra_msg else None}")
                
                if cmd_type == "list":
                    # /sess - 列出会话
                    sessions = await session_mgr.list_sessions(from_user_id, chat_id)
                    reply_msg = session_mgr.format_session_list(sessions)
                    await send_reply(
                        chat_id=chat_id,
                        message=reply_msg,
                        msg_type="text",
                        bot_key=bot.bot_key
                    )
                    return {"errcode": 0, "errmsg": "slash command handled"}
                
                elif cmd_type == "reset":
                    # /reset - 重置会话
                    success = await session_mgr.reset_session(from_user_id, chat_id, bot.bot_key)
                    if success:
                        await send_reply(
                            chat_id=chat_id,
                            message="✅ 会话已重置，下次发送消息将开始新对话",
                            msg_type="text",
                            bot_key=bot.bot_key
                        )
                    else:
                        await send_reply(
                            chat_id=chat_id,
                            message="ℹ️ 当前没有活跃会话",
                            msg_type="text",
                            bot_key=bot.bot_key
                        )
                    return {"errcode": 0, "errmsg": "slash command handled"}
                
                elif cmd_type == "change":
                    # /change <short_id> [message] - 切换会话，可选附带消息
                    target_session = await session_mgr.change_session(from_user_id, chat_id, cmd_arg)
                    if not target_session:
                        await send_reply(
                            chat_id=chat_id,
                            message=f"❌ 未找到会话 `{cmd_arg}`\n使用 `/s` 查看可用会话",
                            msg_type="text",
                            bot_key=bot.bot_key
                        )
                        return {"errcode": 0, "errmsg": "slash command handled"}
                    
                    # 如果有附带消息，继续转发给 Agent
                    if extra_msg:
                        logger.info(f"会话已切换到 {target_session.short_id}，继续转发消息: {extra_msg[:30]}...")
                        content = extra_msg
                    else:
                        await send_reply(
                            chat_id=chat_id,
                            message=f"✅ 已切换到会话 `{target_session.short_id}`\n最后消息: {target_session.last_message or '(无)'}",
                            msg_type="text",
                            bot_key=bot.bot_key
                        )
                        return {"errcode": 0, "errmsg": "slash command handled"}
                
                elif cmd_type in ("ping", "status"):
                    # /ping 或 /status - 系统状态（需要管理员权限）
                    is_admin = await check_is_admin(from_user_id, from_user_alias)
                    if not is_admin:
                        await send_reply(
                            chat_id=chat_id,
                            message="⚠️ 此命令仅限管理员使用",
                            msg_type="text",
                            bot_key=bot.bot_key
                        )
                        return {"errcode": 0, "errmsg": "permission denied"}
                    
                    if cmd_type == "ping":
                        # 简单的 ping 响应
                        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
                        await send_reply(
                            chat_id=chat_id,
                            message=f"🟢 pong! (延迟: {duration_ms}ms)",
                            msg_type="text",
                            bot_key=bot.bot_key
                        )
                    else:
                        # 详细状态信息
                        status_msg = await get_system_status()
                        await send_reply(
                            chat_id=chat_id,
                            message=status_msg,
                            msg_type="text",
                            bot_key=bot.bot_key
                        )
                    return {"errcode": 0, "errmsg": "slash command handled"}
                
                elif cmd_type in ("help", "bots", "bot", "pending", "recent", "errors", "health"):
                    # 其他管理员命令
                    is_admin = await check_is_admin(from_user_id, from_user_alias)
                    if not is_admin:
                        await send_reply(
                            chat_id=chat_id,
                            message="⚠️ 此命令仅限管理员使用",
                            msg_type="text",
                            bot_key=bot.bot_key
                        )
                        return {"errcode": 0, "errmsg": "permission denied"}
                    
                    # 根据命令类型获取响应
                    if cmd_type == "help":
                        response_msg = await get_admin_help()
                    elif cmd_type == "bots":
                        response_msg = await get_bots_list()
                    elif cmd_type == "bot":
                        response_msg = await get_bot_detail(cmd_arg or "")
                    elif cmd_type == "pending":
                        response_msg = await get_pending_list()
                    elif cmd_type == "recent":
                        response_msg = await get_recent_logs()
                    elif cmd_type == "errors":
                        response_msg = await get_error_logs()
                    elif cmd_type == "health":
                        response_msg = await check_agents_health()
                    else:
                        response_msg = f"❓ 未知命令: {cmd_type}"
                    
                    await send_reply(
                        chat_id=chat_id,
                        message=response_msg,
                        msg_type="text",
                        bot_key=bot.bot_key
                    )
                    return {"errcode": 0, "errmsg": "slash command handled"}
        
        # === 会话管理：获取现有 session_id ===
        current_session_id = None
        session_mgr = get_session_manager()
        active_session = await session_mgr.get_active_session(from_user_id, chat_id, bot.bot_key)
        if active_session:
            current_session_id = active_session.session_id
            logger.info(f"找到活跃会话: {active_session.short_id}")
        
        # 获取目标 URL（用于日志）
        target_url = bot.forward_config.get_url()
        
        # 创建日志记录（持久化到数据库）
        log_data = RequestLogData(
            chat_id=chat_id,
            from_user_id=from_user_id,
            from_user_name=from_user_name,
            content=content or "(image)",
            target_url=target_url,
            msg_type=msg_type,
            bot_key=bot.bot_key,
            bot_name=bot.name,
            session_id=current_session_id,
            status="pending"
        )
        log_id = await add_request_log(log_data)
        
        # 生成请求 ID 用于追踪
        import uuid
        request_id = str(uuid.uuid4())[:8]
        
        # 添加到 pending 请求列表
        add_pending_request(
            request_id=request_id,
            bot_name=bot.name,
            user=from_user_name or from_user_id,
            message=content or "(image)"
        )
        
        try:
            # 转发到 Agent（使用 Bot 配置，带上 session_id）
            result = await forward_to_agent_with_bot(
                bot_key=bot.bot_key,
                content=content or "",
                timeout=config.timeout,
                session_id=current_session_id
            )
        finally:
            # 无论成功失败，都从 pending 列表移除
            remove_pending_request(request_id)
        
        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
        
        if not result:
            # 更新日志：转发失败
            if log_id:
                await update_request_log(
                    log_id=log_id,
                    status="error",
                    error="转发失败或无配置",
                    duration_ms=duration_ms
                )
            
            await send_reply(
                chat_id=chat_id,
                message="⚠️ 处理请求时发生错误，请稍后重试",
                msg_type="text",
                bot_key=bot.bot_key
            )
            return {"errcode": 0, "errmsg": "forward failed"}
        
        # === 会话管理：记录 Agent 返回的 session_id ===
        if result.session_id:
            session_mgr = get_session_manager()
            await session_mgr.record_session(
                user_id=from_user_id,
                chat_id=chat_id,
                bot_key=bot.bot_key,
                session_id=result.session_id,
                last_message=content or "(image)"
            )
            logger.info(f"会话已记录: session={result.session_id[:8]}...")
        
        # 发送结果给用户（使用正确的 bot_key）
        send_result = await send_reply(
            chat_id=chat_id,
            message=result.reply,
            msg_type=result.msg_type,
            bot_key=bot.bot_key
        )
        
        # 更新日志：成功或发送失败
        if log_id:
            await update_request_log(
                log_id=log_id,
                status="success" if send_result.get("success") else "error",
                response=result.reply,
                session_id=result.session_id,
                error=send_result.get("error") if not send_result.get("success") else None,
                duration_ms=duration_ms
            )
        
        if send_result.get("success"):
            logger.info(f"回复已发送: chat_id={chat_id}")
        else:
            logger.error(f"发送回复失败: {send_result.get('error')}")
        
        return {"errcode": 0, "errmsg": "ok"}
        
    except Exception as e:
        logger.error(f"处理回调失败: {e}", exc_info=True)
        
        # 尝试更新日志
        if log_id:
            await update_request_log(
                log_id=log_id,
                status="error",
                error=str(e),
                duration_ms=int((datetime.now() - start_time).total_seconds() * 1000)
            )
        
        return {"errcode": -1, "errmsg": str(e)}
