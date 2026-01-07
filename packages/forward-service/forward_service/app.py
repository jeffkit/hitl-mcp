"""
Forward Service 主应用

接收企微机器人回调，转发到目标 URL，并将结果返回给用户。
支持多 chat_id 配置，每个 chat_id 可以有独立的 Agent 配置。

运行方式:
    python -m forward_service.app
    # 或
    uvicorn forward_service.app:app --host 0.0.0.0 --port 8083

配置方式:
    - JSON 文件 (默认): USE_DATABASE=false 或不设置
    - 数据库: USE_DATABASE=true
"""
import os
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from collections import deque
from dataclasses import dataclass, field, asdict

import httpx
from pathlib import Path
from fastapi import FastAPI, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .config import config as config_v1  # 旧配置（兼容）
from .config_v2 import config_v2  # 新配置（JSON 文件）
from .config_db import config_db  # 数据库配置
from .sender import send_reply

# 根据环境变量选择配置方式
USE_DATABASE = os.getenv("USE_DATABASE", "").lower() in ("1", "true", "yes")

if USE_DATABASE:
    from .database import database_lifespan, get_db_manager
    from .session_manager import SessionManager, init_session_manager, get_session_manager
    config = config_db
    logger = logging.getLogger(__name__)
    logger.info("✅ 使用数据库配置 (USE_DATABASE=true)")
else:
    config = config_v2  # JSON 文件配置
    logger = logging.getLogger(__name__)
    logger.info("📄 使用 JSON 文件配置 (USE_DATABASE=false)")

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


# ============== 数据模型 ==============

class ForwardRequest(BaseModel):
    """转发给目标 URL 的请求体（通用格式）"""
    chat_id: str
    chat_type: str
    from_user: dict
    msg_type: str
    content: str | None = None
    image_url: str | None = None
    raw_data: dict | None = None


class ForwardResponse(BaseModel):
    """目标 URL 返回的响应体"""
    reply: str
    msg_type: str = "text"  # text / markdown


# ============== 请求日志（用于管理台） ==============

@dataclass
class RequestLog:
    """请求日志"""
    timestamp: str
    chat_id: str
    from_user: str
    content: str
    target_url: str
    status: str  # success / error
    response: str | None = None
    error: str | None = None
    duration_ms: int = 0


# 最近的请求日志（内存存储，保留最近 100 条）
request_logs: deque[RequestLog] = deque(maxlen=100)


def add_request_log(log: RequestLog):
    """添加请求日志"""
    request_logs.appendleft(log)


# ============== 辅助函数 ==============

def extract_content(data: dict) -> tuple[str | None, str | None]:
    """
    从回调数据中提取消息内容
    
    Args:
        data: 飞鸽回调原始数据
    
    Returns:
        (text_content, image_url)
    """
    msg_type = data.get("msgtype", "")
    
    if msg_type == "text":
        text_data = data.get("text", {})
        content = text_data.get("content", "")
        # 去除 @机器人
        if content.startswith("@"):
            parts = content.split(" ", 1)
            if len(parts) > 1:
                content = parts[1].strip()
        return content, None
    
    elif msg_type == "image":
        image_data = data.get("image", {})
        return None, image_data.get("image_url", "")
    
    elif msg_type == "mixed":
        mixed = data.get("mixed_message", {})
        msg_items = mixed.get("msg_item", [])
        
        contents = []
        images = []
        
        for item in msg_items:
            item_type = item.get("msg_type", "")
            if item_type == "text":
                text = item.get("text", {}).get("content", "")
                # 去除 @机器人
                if text.startswith("@"):
                    parts = text.split(" ", 1)
                    if len(parts) > 1:
                        text = parts[1].strip()
                if text:
                    contents.append(text)
            elif item_type == "image":
                img_url = item.get("image", {}).get("image_url", "")
                if img_url:
                    images.append(img_url)
        
        content = "\n".join(contents) if contents else None
        image_url = images[0] if images else None
        return content, image_url
    
    return None, None


@dataclass
class AgentResult:
    """Agent 响应结果（包含 session_id）"""
    reply: str
    msg_type: str = "text"
    session_id: str | None = None


async def forward_to_agent_with_bot(
    bot_key: str | None,
    content: str,
    timeout: int,
    session_id: str | None = None
) -> AgentResult | None:
    """
    使用指定 Bot 转发消息到 Agent
    
    Args:
        bot_key: Bot Key
        content: 消息内容
        timeout: 超时时间（秒）
        session_id: 会话 ID（可选，用于会话持续性）
    
    Returns:
        AgentResult 或 None
    """
    # 获取 Bot 配置
    bot = config.get_bot_or_default(bot_key)
    if not bot:
        logger.warning(f"未找到 bot_key={bot_key} 的配置，且无默认 Bot")
        return None
    
    # 获取目标 URL
    target_url = bot.forward_config.get_url()
    if not target_url:
        logger.warning(f"Bot {bot.name} 的 forward_config.url_template 未配置")
        return None
    
    # 获取 API Key
    api_key = bot.forward_config.api_key
    
    # 使用 Bot 自己的 timeout（如果配置了）
    bot_timeout = bot.forward_config.timeout or timeout
    
    logger.info(f"转发消息到 Agent: url={target_url}, session_id={session_id[:8] if session_id else 'None'}...")
    
    # 构建请求头
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    
    # 构建请求体（AgentStudio 格式）
    request_body = {"message": content}
    if session_id:
        # 使用 camelCase 格式以匹配 Agent 期望
        request_body["sessionId"] = session_id
    
    start_time = datetime.now()
    
    try:
        async with httpx.AsyncClient(timeout=bot_timeout) as client:
            response = await client.post(
                target_url,
                json=request_body,
                headers=headers
            )
            
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            
            if response.status_code != 200:
                logger.error(f"Agent 返回错误: status={response.status_code}, body={response.text[:200]}")
                return AgentResult(
                    reply=f"⚠️ Agent 返回错误\n状态码: {response.status_code}\n响应: {response.text[:200]}",
                    msg_type="text"
                )
            
            result = response.json()
            logger.info(f"Agent 响应: {str(result)[:200]}")
            
            # 提取 session_id（Agent 可能返回新的 session_id）
            response_session_id = result.get("session_id") or result.get("sessionId") or session_id
            
            # 适配 AgentStudio 响应格式: {"response": "..."}
            if "response" in result:
                return AgentResult(
                    reply=result["response"],
                    msg_type="text",
                    session_id=response_session_id
                )
            
            # 兼容标准格式: {"reply": "...", "msg_type": "..."}
            if "reply" in result:
                return AgentResult(
                    reply=result.get("reply", ""),
                    msg_type=result.get("msg_type", "text"),
                    session_id=response_session_id
                )
            
            # 兼容其他格式
            if "data" in result or "json" in result:
                raw_data = result.get("json") or result.get("data", {})
                return AgentResult(
                    reply=f"✅ 消息已处理\n\n响应数据:\n```\n{raw_data}\n```",
                    msg_type="text",
                    session_id=response_session_id
                )
            
            # 默认返回原始响应
            import json as json_module
            return AgentResult(
                reply=f"✅ Agent 响应:\n```\n{json_module.dumps(result, ensure_ascii=False, indent=2)[:500]}\n```",
                msg_type="text",
                session_id=response_session_id
            )
            
    except httpx.TimeoutException:
        logger.error(f"转发请求超时: {target_url}")
        return AgentResult(
            reply="⚠️ 请求超时，Agent 响应时间过长",
            msg_type="text"
        )
    except Exception as e:
        logger.error(f"转发请求失败: {e}", exc_info=True)
        return AgentResult(
            reply=f"⚠️ 请求失败: {str(e)}",
            msg_type="text"
        )


# ============== FastAPI 应用 ==============

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 数据库配置需要初始化数据库
    if USE_DATABASE:
        async with database_lifespan():
            # 初始化配置
            await config.initialize()

            # 初始化会话管理器
            init_session_manager(get_db_manager())
            logger.info("  会话管理器已初始化")

            # 验证配置
            errors = config.validate()
            if errors:
                for error in errors:
                    logger.warning(f"配置警告: {error}")

            logger.info(f"Forward Service 启动（数据库模式 v3.0）")
            logger.info(f"  端口: {config.port}")
            logger.info(f"  默认 Bot Key: {config.default_bot_key[:10]}..." if config.default_bot_key else "  默认 Bot Key: 未配置")
            logger.info(f"  Bot 数量: {len(config.bots)}")

            # 列出所有 Bot
            for bot_key, bot in config.bots.items():
                logger.info(f"  - {bot.name} (key={bot_key[:10]}..., enabled={bot.enabled})")

            yield

            logger.info("Forward Service 关闭")
    else:
        # JSON 配置模式
        errors = config.validate()
        if errors:
            for error in errors:
                logger.warning(f"配置警告: {error}")

        logger.info(f"Forward Service 启动（JSON 配置模式 v2.0）")
        logger.info(f"  端口: {config.port}")
        logger.info(f"  默认 Bot Key: {config.default_bot_key[:10]}..." if config.default_bot_key else "  默认 Bot Key: 未配置")
        logger.info(f"  Bot 数量: {len(config.bots)}")

        # 列出所有 Bot
        for bot_key, bot in config.bots.items():
            logger.info(f"  - {bot.name} (key={bot_key[:10]}..., enabled={bot.enabled})")

        yield

        logger.info("Forward Service 关闭")


# 创建 FastAPI 应用
app = FastAPI(
    title="Forward Service",
    description="消息转发服务 - 接收企微回调，转发到 Agent",
    version="2.0.0" if USE_DATABASE else "1.1.0",
    lifespan=lifespan
)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 静态文件目录
STATIC_DIR = Path(__file__).parent / "static"


@app.get("/")
async def root():
    """根路径"""
    return {
        "service": "Forward Service",
        "version": "1.1.0",
        "status": "running"
    }


@app.get("/admin")
async def admin_page():
    """管理台页面"""
    admin_html = STATIC_DIR / "admin.html"
    if admin_html.exists():
        return FileResponse(admin_html)
    return {"error": "Admin page not found"}


@app.get("/health")
async def health():
    """健康检查"""
    errors = config.validate()
    return {
        "status": "healthy" if not errors else "unhealthy",
        "config_errors": errors,
        "default_bot_key": config.default_bot_key[:10] + "..." if config.default_bot_key else None,
        "bots_count": len(config.bots),
        "version": "2.0.0"
    }


# ============== 管理台 API ==============

@app.get("/admin/status")
async def admin_status():
    """获取服务状态（管理台用）"""
    return {
        "service": "Forward Service",
        "version": "2.0.0",  # 升级到 2.0（多 Bot 支持）
        "config": {
            "default_bot_key": config.default_bot_key[:10] + "..." if config.default_bot_key else None,
            "bots_count": len(config.bots),
            "timeout": config.timeout,
            "port": config.port
        },
        "stats": {
            "total_requests": len(request_logs),
            "recent_success": sum(1 for log in request_logs if log.status == "success"),
            "recent_error": sum(1 for log in request_logs if log.status == "error")
        }
    }


@app.get("/admin/config")
async def get_config():
    """获取完整配置（管理台用）"""
    return config.get_config_dict()


@app.put("/admin/config")
async def update_config(request: Request):
    """更新完整配置（管理台用）"""
    try:
        data = await request.json()

        # 数据库配置需要异步更新
        if USE_DATABASE:
            result = await config.update_from_dict(data)
        else:
            result = config.update_from_dict(data)

        return result
    except Exception as e:
        logger.error(f"更新配置失败: {e}")
        return {"success": False, "error": str(e)}


@app.post("/admin/config/reload")
async def reload_config():
    """重新加载配置"""
    # 数据库配置需要异步重载
    if USE_DATABASE:
        return await config.reload_config()
    else:
        return config.reload_config()


# ============== 兼容性 API（旧版规则管理） ==============

@app.get("/admin/rules")
async def admin_rules():
    """
    获取所有 Bot 配置（兼容旧 API）
    
    为了与旧版管理台兼容，将 bots 格式转换为类似 rules 的格式
    以 bot_key 作为 key，bot 配置作为 value
    """
    # 新格式：返回 bots 数据，但保持向后兼容
    bots_dict = {}
    
    for bot_key, bot in config.bots.items():
        # 将 bot 配置转换为类似旧 rule 的格式
        bots_dict[bot_key] = {
            "url_template": bot.forward_config.url_template,
            "agent_id": bot.forward_config.agent_id,
            "api_key": bot.forward_config.api_key,
            "name": bot.name,
            "timeout": bot.forward_config.timeout,
            # 额外信息
            "bot_name": bot.name,
            "description": bot.description,
            "access_mode": bot.access_control.mode,
            "enabled": bot.enabled,
            "is_default": bot_key == config.default_bot_key
        }
    
    return {
        "default_url": config.default_bot_key,  # 返回默认 bot_key（兼容）
        "default_bot_key": config.default_bot_key,
        "rules": bots_dict,  # 保持 rules 字段名（兼容）
        "bots": bots_dict  # 同时提供 bots 字段（新）
    }


@app.get("/admin/logs")
async def admin_logs(limit: int = 20):
    """获取最近的请求日志（管理台用）"""
    logs = list(request_logs)[:limit]
    return {
        "total": len(request_logs),
        "logs": [asdict(log) for log in logs]
    }


# ============== Bot 管理 API（V2 - 数据库模式专用）=============

@app.get("/admin/mode")
async def get_mode():
    """
    获取当前配置模式（管理台用）

    返回:
        mode: "database" | "json"
        supports_bot_api: 是否支持新的 Bot 管理 API
    """
    return {
        "mode": "database" if USE_DATABASE else "json",
        "supports_bot_api": USE_DATABASE,
        "version": "2.0.0" if USE_DATABASE else "1.1.0"
    }


@app.get("/admin/bots")
async def list_bots():
    """
    获取所有 Bot 列表

    仅数据库模式支持此 API
    """
    if not USE_DATABASE:
        return {
            "success": False,
            "error": "JSON 模式不支持 Bot 管理 API，请使用 /admin/config 管理配置"
        }

    bots = await config.list_bots()
    return {
        "success": True,
        "bots": bots,
        "total": len(bots)
    }


@app.get("/admin/bots/{bot_key}")
async def get_bot_by_key(bot_key: str):
    """
    获取单个 Bot 详情

    仅数据库模式支持此 API
    """
    if not USE_DATABASE:
        return {
            "success": False,
            "error": "JSON 模式不支持此操作"
        }

    bot = await config.get_bot(bot_key)
    if not bot:
        return {
            "success": False,
            "error": f"Bot '{bot_key}' 不存在"
        }

    return {
        "success": True,
        "bot": bot
    }


@app.post("/admin/bots")
async def create_bot(request: Request):
    """
    创建新 Bot

    仅数据库模式支持此 API

    Body:
        bot_key: str (必填)
        name: str (必填)
        url_template: str (必填)
        description: str
        agent_id: str
        api_key: str
        timeout: int
        access_mode: str
        enabled: bool
        whitelist: list[str]
        blacklist: list[str]
    """
    if not USE_DATABASE:
        return {
            "success": False,
            "error": "JSON 模式不支持此操作，请使用 /admin/config 管理配置"
        }

    try:
        data = await request.json()
        result = await config.create_bot(data)
        return result
    except Exception as e:
        logger.error(f"创建 Bot 失败: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


@app.put("/admin/bots/{bot_key}")
async def update_bot_by_key(bot_key: str, request: Request):
    """
    更新 Bot 配置

    仅数据库模式支持此 API

    Body: 同 create_bot，所有字段都是可选的
    """
    if not USE_DATABASE:
        return {
            "success": False,
            "error": "JSON 模式不支持此操作，请使用 /admin/config 管理配置"
        }

    try:
        data = await request.json()
        result = await config.update_bot(bot_key, data)
        return result
    except Exception as e:
        logger.error(f"更新 Bot 失败: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


@app.delete("/admin/bots/{bot_key}")
async def delete_bot_by_key(bot_key: str):
    """
    删除 Bot

    仅数据库模式支持此 API
    """
    if not USE_DATABASE:
        return {
            "success": False,
            "error": "JSON 模式不支持此操作，请使用 /admin/config 管理配置"
        }

    result = await config.delete_bot(bot_key)
    return result


# ============== 回调处理 ==============

@app.post("/callback")
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
    log_entry = None
    
    try:
        data = await request.json()
        
        chat_id = data.get("chatid", "")
        chat_type = data.get("chattype", "group")
        msg_type = data.get("msgtype", "")
        from_user = data.get("from", {})
        from_user_name = from_user.get("name", "unknown")
        from_user_id = from_user.get("userid", "unknown")
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
            # 此时无法确定用哪个 bot，使用旧配置的默认 bot_key（兜底）
            await send_reply(
                chat_id=chat_id,
                message="⚠️ Bot 配置错误，请联系管理员",
                msg_type="text"
            )
            return {"errcode": 0, "errmsg": "no bot config"}
        
        logger.info(f"使用 Bot: {bot.name} (key={bot.bot_key[:10]}...)")
        
        # === 访问控制检查 ===
        allowed, reason = config.check_access(bot, from_user_id)
        if not allowed:
            logger.warning(f"用户 {from_user_name} ({from_user_id}) 被拒绝访问 Bot {bot.name}: {reason}")
            
            # 尝试回退到默认 Bot
            if bot.bot_key != config.default_bot_key:
                logger.info(f"尝试回退到默认 Bot: {config.default_bot_key}")
                default_bot = config.get_bot(config.default_bot_key)
                if default_bot:
                    default_allowed, default_reason = config.check_access(default_bot, from_user_id)
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
        if USE_DATABASE and content:
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
                        # 将 content 替换为附带的消息，继续后续的转发流程
                        content = extra_msg
                    else:
                        # 没有附带消息，只显示切换成功
                        await send_reply(
                            chat_id=chat_id,
                            message=f"✅ 已切换到会话 `{target_session.short_id}`\n最后消息: {target_session.last_message or '(无)'}",
                            msg_type="text",
                            bot_key=bot.bot_key
                        )
                        return {"errcode": 0, "errmsg": "slash command handled"}
        
        # === 会话管理：获取现有 session_id ===
        current_session_id = None
        if USE_DATABASE:
            session_mgr = get_session_manager()
            active_session = await session_mgr.get_active_session(from_user_id, chat_id, bot.bot_key)
            if active_session:
                current_session_id = active_session.session_id
                logger.info(f"找到活跃会话: {active_session.short_id}")
        
        # 获取目标 URL（用于日志）
        target_url = bot.forward_config.get_url()
        
        # 初始化日志条目
        log_entry = RequestLog(
            timestamp=datetime.now().isoformat(),
            chat_id=chat_id,
            from_user=from_user_name,
            content=content or "(image)",
            target_url=target_url,
            status="pending"
        )
        
        # 转发到 Agent（使用 Bot 配置，带上 session_id）
        result = await forward_to_agent_with_bot(
            bot_key=bot.bot_key,
            content=content or "",
            timeout=config.timeout,
            session_id=current_session_id
        )
        
        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
        
        if not result:
            log_entry.status = "error"
            log_entry.error = "转发失败或无配置"
            log_entry.duration_ms = duration_ms
            add_request_log(log_entry)
            
            # 发送错误提示给用户（使用正确的 bot_key）
            await send_reply(
                chat_id=chat_id,
                message="⚠️ 处理请求时发生错误，请稍后重试",
                msg_type="text",
                bot_key=bot.bot_key
            )
            return {"errcode": 0, "errmsg": "forward failed"}
        
        # === 会话管理：记录 Agent 返回的 session_id ===
        if USE_DATABASE and result.session_id:
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
        
        # 更新日志
        log_entry.status = "success" if send_result.get("success") else "error"
        log_entry.response = result.reply[:200] if result.reply else None
        log_entry.duration_ms = duration_ms
        if not send_result.get("success"):
            log_entry.error = send_result.get("error")
        add_request_log(log_entry)
        
        if send_result.get("success"):
            logger.info(f"回复已发送: chat_id={chat_id}")
        else:
            logger.error(f"发送回复失败: {send_result.get('error')}")
        
        return {"errcode": 0, "errmsg": "ok"}
        
    except Exception as e:
        logger.error(f"处理回调失败: {e}", exc_info=True)
        
        if log_entry:
            log_entry.status = "error"
            log_entry.error = str(e)
            log_entry.duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            add_request_log(log_entry)
        
        return {"errcode": -1, "errmsg": str(e)}


def main():
    """主函数"""
    import uvicorn
    uvicorn.run(
        "forward_service.app:app",
        host="0.0.0.0",
        port=config.port,
        reload=False
    )


if __name__ == "__main__":
    main()
