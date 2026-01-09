"""
回调处理路由

处理企微机器人回调
"""
import logging
from datetime import datetime

from fastapi import APIRouter, Request, Header

from ..config import config
from ..sender import send_reply
from ..session_manager import get_session_manager
from ..utils import extract_content
from ..services import forward_to_agent_with_bot
from .admin import add_request_log, update_request_log, RequestLogData
from .admin_commands import (
    check_is_admin,
    get_system_status,
    get_admin_help,
    get_bots_list,
    get_bot_detail,
    update_bot_config,
    get_pending_list,
    get_recent_logs,
    get_error_logs,
    check_agents_health,
    add_pending_request,
    remove_pending_request,
)

logger = logging.getLogger(__name__)


# ============== 路由定义 ==============

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
                    # /sess - 列出会话（只列出当前 Bot 的会话）
                    sessions = await session_mgr.list_sessions(from_user_id, chat_id, bot_key=bot.bot_key)
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
                    target_session = await session_mgr.change_session(from_user_id, chat_id, cmd_arg, bot_key=bot.bot_key)
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
                        # extra_msg 格式可能是 "field_type:value"
                        if extra_msg and ":" in extra_msg:
                            parts = extra_msg.split(":", 1)
                            field_type, field_value = parts[0], parts[1]
                            response_msg = await update_bot_config(cmd_arg or "", field_type, field_value)
                        else:
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
