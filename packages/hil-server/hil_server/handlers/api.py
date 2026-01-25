"""
HTTP API 处理器

提供给 MCP Server 调用的 HTTP 接口
支持两种模式：
- relay: 通过 WebSocket 转发给 Worker
- direct: 直接调用 fly-pigeon
"""
import logging
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel

from ..config import config
from ..ws_manager import ws_manager
from ..storage import storage
from ..sender import send_message_direct
from ..idle_hint_config import idle_hint_config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["API"])


# ============== 请求/响应模型 ==============

class SendMessageRequest(BaseModel):
    """发送消息请求"""
    message: str
    chat_id: str | None = None
    chat_type: str = "group"
    images: list[str] | None = None
    mention_list: list[str] | None = None
    project_name: str | None = None
    timeout: int | None = None  # 会话超时时间（秒）
    wait_reply: bool = True  # 是否等待回复（False 则不创建会话）


class SendMessageResponse(BaseModel):
    """发送消息响应"""
    success: bool
    session_id: str | None = None
    message: str = ""
    error: str | None = None


class PollResponse(BaseModel):
    """轮询响应"""
    session_id: str | None = None
    status: str  # waiting, replied, timeout, error
    has_reply: bool = False
    replies: list[dict] = []
    message: str = ""
    error: str | None = None


class UploadImageResponse(BaseModel):
    """上传图片响应"""
    success: bool
    image_url: str | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str
    mode: str  # relay / direct
    worker_connected: bool | None = None
    worker_count: int | None = None


# ============== API 接口 ==============

@router.get("/health", response_model=HealthResponse)
async def health_check():
    """健康检查"""
    if config.is_direct_mode:
        return HealthResponse(
            status="healthy",
            mode="direct",
            worker_connected=None,
            worker_count=None
        )
    else:
        return HealthResponse(
            status="healthy",
            mode="relay",
            worker_connected=ws_manager.has_worker,
            worker_count=len(ws_manager._workers)
        )


@router.post("/send", response_model=SendMessageResponse)
async def send_message(request: SendMessageRequest):
    """
    发送消息
    
    根据配置的模式：
    - direct: 直接调用 fly-pigeon
    - relay: 通过 WebSocket 转发给 Worker
    """
    if not request.chat_id:
        return SendMessageResponse(
            success=False,
            error="未指定 chat_id"
        )
    
    # Relay 模式检查 Worker 连接
    if not config.is_direct_mode and not ws_manager.has_worker:
        return SendMessageResponse(
            success=False,
            error="没有可用的 Worker 连接，请确保 DevCloud Worker 已启动"
        )
    
    try:
        timeout = request.timeout or 300
        session = None
        short_id = ""
        
        # 查询 chat_type（从数据库）
        chat_type = request.chat_type  # 默认使用请求中的值
        if storage._use_database and storage._db_manager:
            try:
                from ..chat_info_repo import get_chat_info_repository
                async with storage._db_manager.session() as db:
                    chat_info_repo = get_chat_info_repository(db)
                    chat_info = await chat_info_repo.get_by_chat_id(request.chat_id)
                    if chat_info:
                        chat_type = chat_info.chat_type
                        logger.info(f"从数据库查询到 chat_type: {chat_type} for chat_id={request.chat_id[:20]}...")
                    else:
                        logger.info(f"数据库中未找到 chat_id={request.chat_id[:20]}..., 使用默认 chat_type={chat_type}")
            except Exception as e:
                logger.warning(f"查询 chat_type 失败，使用默认值: {e}")
        
        # 1. 只有需要等待回复时才创建会话
        if request.wait_reply:
            session = await storage.create_session(
                chat_id=request.chat_id,
                chat_type=chat_type,  # 使用查询到的 chat_type
                message=request.message,
                project_name=request.project_name or "",
                images=request.images,
                timeout=timeout
            )
            short_id = session.short_id
            logger.info(f"创建会话: session_id={session.session_id}, short_id={short_id}, mode={config.effective_mode}")
        else:
            logger.info(f"仅发送消息（不等待回复）: chat_id={request.chat_id}, mode={config.effective_mode}")
        
        # 2. 根据模式发送消息
        if config.is_direct_mode:
            # Direct 模式：直接调用 fly-pigeon
            result = await send_message_direct(
                short_id=short_id,
                message=request.message,
                chat_id=request.chat_id,
                project_name=request.project_name,
                images=request.images,
                chat_type=request.chat_type,
                wait_reply=request.wait_reply,
            )
        else:
            # Relay 模式：通过 WebSocket 转发给 Worker
            payload = {
                "short_id": short_id,
                "message": request.message,
                "chat_id": request.chat_id,
                "chat_type": request.chat_type,
                "images": request.images,
                "project_name": request.project_name,
                "wait_reply": request.wait_reply,
            }
            
            result = await ws_manager.send_request(
                action="send_message",
                payload=payload,
                timeout=min(timeout, 60)
            )
        
        if not result.get("success", True):
            if session:
                await storage.mark_timeout(session.session_id)
            return SendMessageResponse(
                success=False,
                error=result.get("error", "发送失败")
            )
        
        return SendMessageResponse(
            success=True,
            session_id=session.session_id if session else None,
            message="消息发送成功"
        )
        
    except Exception as e:
        logger.error(f"发送消息失败: {e}", exc_info=True)
        return SendMessageResponse(
            success=False,
            error=str(e)
        )


@router.get("/poll/{session_id}", response_model=PollResponse)
async def poll_replies(session_id: str):
    """
    轮询获取用户回复
    """
    session = await storage.get_session(session_id)
    
    if not session:
        return PollResponse(
            session_id=session_id,
            status="not_found",
            has_reply=False,
            replies=[],
            message="会话不存在或已过期"
        )
    
    has_reply = session.status == "replied" and len(session.replies) > 0
    
    return PollResponse(
        session_id=session_id,
        status=session.status,
        has_reply=has_reply,
        replies=session.replies,
        message=f"会话状态: {session.status}"
    )


@router.post("/session/{session_id}/timeout")
async def mark_session_timeout(session_id: str):
    """标记会话超时"""
    success = await storage.mark_timeout(session_id)
    return {"success": success}


# ============== Direct 模式：回调接口 ==============

from fastapi import Request, Header

@router.post("/callback")
async def handle_callback(
    request: Request,
    x_api_key: str | None = Header(None, alias="x-api-key")
):
    """
    处理飞鸽传书的回调（Direct 模式）
    
    在 Relay 模式下，回调由 Worker 接收并转发。
    在 Direct 模式下，回调直接发送到这个接口。
    """
    try:
        data = await request.json()
        logger.info(f"收到飞鸽回调: chatid={data.get('chatid')}, msgtype={data.get('msgtype')}")
        
        chat_id = data.get("chatid", "")
        chat_type = data.get("chattype", "group")
        from_user = data.get("from", {})
        
        # 检查是否是 slash 命令
        if data.get("msgtype") == "text":
            text_data = data.get("text", {})
            content = text_data.get("content", "").strip()
            
            # 去除 @机器人 前缀
            if content.startswith("@"):
                parts = content.split(" ", 1)
                if len(parts) > 1:
                    content = parts[1].strip()
            
            # 处理 slash 命令
            from .slash_commands import process_slash_command
            slash_response = await process_slash_command(
                command=content,
                chat_id=chat_id,
                user_id=from_user.get("userid", ""),
                user_alias=from_user.get("alias", ""),
                from_user=from_user
            )
            
            if slash_response:
                # 是 slash 命令，发送响应
                await send_message_direct(
                    short_id="",
                    message=slash_response,
                    chat_id=chat_id,
                    project_name=None,
                    images=None,
                    wait_reply=False,
                    chat_type=chat_type,
                )
                return {"errcode": 0, "errmsg": "slash command handled"}
        
        # 使用 storage 的回调处理逻辑
        result = await storage.handle_callback(data)
        
        # 记录 Chat 信息（chat_id -> chat_type 映射）
        # 无论回调是否成功匹配到会话，都记录 chat_type
        if storage._use_database and storage._db_manager:
            try:
                from ..chat_info_repo import get_chat_info_repository
                async with storage._db_manager.session() as db:
                    chat_info_repo = get_chat_info_repository(db)
                    await chat_info_repo.record_chat(
                        chat_id=chat_id,
                        chat_type=chat_type,
                        chat_name=None,  # 企微回调暂不提供群名
                        bot_key=None  # HIL Server 不管理多 Bot
                    )
                    await db.commit()
            except Exception as e:
                # 记录失败不影响主流程
                logger.warning(f"记录 chat_type 失败: {e}")
        
        if result.get("success"):
            logger.info(f"回调处理成功: session_id={result.get('session_id')}")
        else:
            error = result.get("error", "unknown")
            
            if error == "no_waiting_session":
                logger.warning(f"未找到等待中的会话: chat_id={chat_id}")
                # Direct 模式：直接发送空闲提示消息
                await _send_idle_hint_direct(chat_id, chat_type, from_user, data)
            elif error.startswith("multiple_sessions"):
                logger.warning(f"多个等待中的会话，需要用户引用回复")
                # Direct 模式：发送多会话提示
                sessions = result.get("waiting_sessions", [])
                await _send_multiple_sessions_hint_direct(chat_id, sessions, from_user, chat_type)
            else:
                logger.warning(f"回调处理: {error}")
        
        return {"errcode": 0, "errmsg": "ok"}
        
    except Exception as e:
        logger.error(f"处理回调失败: {e}", exc_info=True)
        return {"errcode": -1, "errmsg": str(e)}


async def _send_idle_hint_direct(chat_id: str, chat_type: str, from_user: dict, callback_data: dict):
    """Direct 模式：发送空闲提示消息"""
    message_template = idle_hint_config.get_message_template(chat_id)
    
    if not message_template:
        logger.info(f"空闲提示已禁用: chat_id={chat_id}")
        return
    
    config_entry = type('obj', (object,), {
        'enabled': True,
        'message_template': message_template
    })()
    
    if not config_entry or not config_entry.enabled:
        logger.info(f"空闲提示已禁用: chat_id={chat_id}")
        return
    
    user_name = from_user.get("name", "用户")
    chat_type_cn = "群聊" if chat_type == "group" else "私聊"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 使用简单的字符串替换，避免 .format() 对模板中的 JSON 示例 {} 报错
    message = config_entry.message_template
    message = message.replace("{user_name}", user_name)
    message = message.replace("{chat_id}", chat_id)
    message = message.replace("{chat_type}", chat_type_cn)
    message = message.replace("{timestamp}", timestamp)
    
    logger.info(f"发送空闲提示消息: chat_id={chat_id}")
    await send_message_direct(
        short_id="",
        message=message,
        chat_id=chat_id,
        project_name=None,
        images=None,
        wait_reply=False,
        chat_type=chat_type,
    )


async def _send_multiple_sessions_hint_direct(chat_id: str, sessions: list, from_user: dict, chat_type: str = "group"):
    """Direct 模式：发送多会话提示消息"""
    user_name = from_user.get("name", "用户")
    
    # 构建会话列表
    session_list = "\n".join([
        f"  [{i+1}] **{s.get('project_name', '未命名项目')}** - `[#{s['short_id']}]`"
        for i, s in enumerate(sessions)
    ])
    
    message = f"""👋 {user_name}，检测到有 **{len(sessions)}** 个项目正在等待你的回复：

{session_list}

📌 **如何回复特定项目：**
请使用「引用回复」功能，引用对应项目的消息后再回复。

或者在回复中包含项目的短 ID，例如：
`[#abc123] 你的回复内容`"""
    
    logger.info(f"发送多会话提示: chat_id={chat_id}, sessions={len(sessions)}")
    await send_message_direct(
        short_id="",
        message=message,
        chat_id=chat_id,
        project_name=None,
        images=None,
        wait_reply=False,
        chat_type=chat_type,
    )


@router.post("/upload-image", response_model=UploadImageResponse)
async def upload_image(file: UploadFile = File(...)):
    """
    上传图片
    
    - direct 模式：直接转换为 data URL
    - relay 模式：转发到 Worker 处理
    """
    # Relay 模式检查 Worker 连接
    if not config.is_direct_mode and not ws_manager.has_worker:
        return UploadImageResponse(
            success=False,
            error="没有可用的 Worker 连接"
        )
    
    try:
        # 读取图片内容
        content = await file.read()
        
        import base64
        b64_content = base64.b64encode(content).decode("utf-8")
        content_type = file.content_type or "image/png"
        
        if config.is_direct_mode:
            # Direct 模式：直接返回 data URL
            data_url = f"data:{content_type};base64,{b64_content}"
            return UploadImageResponse(
                success=True,
                image_url=data_url
            )
        else:
            # Relay 模式：发送到 Worker
            response = await ws_manager.send_request(
                action="upload_image",
                payload={
                    "content": b64_content,
                    "content_type": content_type,
                    "filename": file.filename
                },
                timeout=30
            )
            
            return UploadImageResponse(
                success=True,
                image_url=response.get("image_url")
            )
        
    except Exception as e:
        logger.error(f"上传图片失败: {e}", exc_info=True)
        return UploadImageResponse(
            success=False,
            error=str(e)
        )
