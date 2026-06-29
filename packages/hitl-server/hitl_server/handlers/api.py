"""
HTTP API 处理器

提供给 MCP Server 调用的 HTTP 接口
支持两种模式：
- relay: 通过 WebSocket 转发给 Worker
- direct: 直接调用 fly-pigeon
"""
import logging
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, HTTPException, Request, Header, Query
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
    bot_key: str | None = None        # 指定目标 bot（ilink/wecom-aibot 多上游路由用）
    upstream: str | None = None       # 指定上游类型：fly-pigeon | ilink | wecom-aibot（冗余校验）


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
    # 安全拦截：fly-pigeon 在没有 chat_id 时会群发至所有群，必须阻止。
    # ilink / wecom-aibot 走各自 Worker，无 chat_id 时由 Worker 自行解析收件人，不受此限。
    is_flypigeon = request.upstream in (None, "fly-pigeon")
    if is_flypigeon and not request.chat_id:
        logger.warning(
            f"[安全拦截] /api/send 被拒绝：未指定 chat_id（防止群发）| "
            f"message_preview={request.message[:80]!r}"
        )
        return SendMessageResponse(
            success=False,
            error="禁止发送：未指定 chat_id，fly-pigeon 在没有 chat_id 时会群发至所有群"
        )
    
    # 内置引擎查询（进程内引擎优先于 direct/relay）
    from ..engines import engine_manager
    _engine = engine_manager.get_by_bot_key(request.bot_key or "") or (
        engine_manager.get_by_type(request.upstream) if request.upstream else None
    )

    # 内置引擎未启动：ilink / wecom-aibot 走进程内引擎，若未在管理台初始化则给出明确引导
    if not _engine and request.upstream in ("ilink", "wecom-aibot"):
        return SendMessageResponse(
            success=False,
            error=f"engine_not_started: {request.upstream} 引擎未启动，请在管理台初始化"
        )

    # Relay 模式检查 Worker 连接（内置引擎命中时跳过——不依赖外部 Worker）
    if not _engine and not config.is_direct_mode and not ws_manager.has_worker:
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
        _cid_preview = (request.chat_id or "")[:20]
        logger.info(f"准备查询 chat_type: chat_id={_cid_preview}..., use_db={storage._use_database}, has_db_manager={storage._db_manager is not None}")
        if storage._use_database and storage._db_manager and request.chat_id:
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
                logger.warning(f"查询 chat_type 失败，使用默认值: {e}", exc_info=True)
        
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
        if _engine:
            # 内置引擎：进程内直接调用（不走 direct/relay/WS）
            payload = {
                "short_id": short_id,
                "message": request.message,
                "chat_id": request.chat_id,
                "chat_type": request.chat_type,
                "images": request.images,
                "project_name": request.project_name,
                "wait_reply": request.wait_reply,
            }
            result = await _engine.send_message(payload)
        elif config.is_direct_mode:
            # Direct 模式：直接调用 fly-pigeon
            result = await send_message_direct(
                short_id=short_id,
                message=request.message,
                chat_id=request.chat_id,
                project_name=request.project_name,
                images=request.images,
                chat_type=chat_type,  # 使用查询到的 chat_type，而不是 request.chat_type
                wait_reply=request.wait_reply,
                mention_list=request.mention_list,
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
                timeout=min(timeout, 60),
                bot_key=request.bot_key,
                worker_type=request.upstream,
            )
        
        if not result.get("success", True):
            if session:
                await storage.mark_timeout(session.session_id)
            return SendMessageResponse(
                success=False,
                error=result.get("error", "发送失败")
            )

        # iLink / wecom-aibot 等在发送时未指定 chat_id 的场景：
        # Worker 解析出实际收件人 openid 后在响应中回传 chat_id，
        # 据此更新 session.chat_id，使后续用户回复能按 chat_id 匹配到会话。
        # 注意：ws_manager.send_request 返回值即 Worker 响应的 data dict 本身。
        if session and not request.chat_id:
            resolved_chat_id = result.get("chat_id") if isinstance(result, dict) else None
            if resolved_chat_id:
                await storage.update_chat_id(session.session_id, resolved_chat_id)

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
        
        chat_id = data.get("chatid", "")
        chat_type = data.get("chattype", "group")
        from_user = data.get("from", {})
        msg_type = data.get("msgtype", "")
        user_name = from_user.get("name", "unknown")
        user_alias = from_user.get("alias", "")
        
        # 提取消息内容摘要（用于调试）
        content_preview = ""
        if msg_type == "text":
            raw_content = data.get("text", {}).get("content", "")
            content_preview = raw_content[:80].replace('\n', '\\n')
        elif msg_type == "mixed":
            items = data.get("mixed_message", {}).get("msg_item", [])
            text_items = [i.get("text", {}).get("content", "")[:40] for i in items if i.get("msg_type") == "text"]
            content_preview = " | ".join(text_items)[:80]
        
        logger.info(
            f"收到飞鸽回调: chatid={chat_id[:20]}..., msgtype={msg_type}, "
            f"from={user_name}({user_alias}), content={content_preview!r}"
        )
        
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
        logger.info(f"准备记录 chat_info: chat_id={chat_id[:20]}..., chat_type={chat_type}, use_db={storage._use_database}")
        if storage._use_database and storage._db_manager:
            try:
                from ..chat_info_repo import get_chat_info_repository
                async with storage._db_manager.session() as db:
                    chat_info_repo = get_chat_info_repository(db)
                    await chat_info_repo.record_chat(
                        chat_id=chat_id,
                        chat_type=chat_type,
                        chat_name=None,  # 企微回调暂不提供群名
                        bot_key=None  # HITL Server 不管理多 Bot
                    )
                    await db.commit()
                logger.info(f"成功记录 chat_info: chat_id={chat_id[:20]}..., chat_type={chat_type}")
            except Exception as e:
                # 记录失败不影响主流程
                logger.warning(f"记录 chat_type 失败: {e}", exc_info=True)
        
        if result.get("success"):
            matched_sid = result.get('session_id', '')
            match_method = result.get('match_method', 'unknown')
            logger.info(
                f"回调处理成功: session_id={matched_sid}, "
                f"match_method={match_method}, from={user_name}"
            )
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


# ============== iLink 登录 ==============
# 优先调内置 ilink 引擎（进程内）；未启用时回退到 WS 外部 ilink-worker。


def _ilink_engine(bot_key: str):
    """查找内置 ilink 引擎（按 bot_key 精确匹配，否则取任一 ilink 引擎）。"""
    from ..engines import engine_manager
    return engine_manager.get_by_bot_key(bot_key) or engine_manager.get_by_type("ilink")


@router.get("/ilink/qr")
async def ilink_get_qr(bot_key: str = Query("", description="ilink worker 的 bot_key")):
    """获取 iLink 扫码二维码。

    优先调内置 ilink 引擎；未启用则通过 WS 转发给外部 ilink-worker。
    返回: { status, qr_url, qr_base64, qrcode_key, error? }
    """
    engine = _ilink_engine(bot_key)
    if engine:
        return await engine.get_qr()
    try:
        result = await ws_manager.send_request(
            action="get_qr",
            payload={"bot_key": bot_key},
            timeout=20.0,
            bot_key=bot_key or None,
            worker_type="ilink",
        )
        return result
    except Exception as e:
        logger.error(f"获取 iLink 二维码失败: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


@router.get("/ilink/login_status")
async def ilink_login_status(bot_key: str = Query("", description="ilink worker 的 bot_key")):
    """查询 iLink 登录状态。

    返回: { status: "pending" | "success" | "expired" | "not_started" | "error" }
    """
    engine = _ilink_engine(bot_key)
    if engine:
        return await engine.get_login_status()
    try:
        result = await ws_manager.send_request(
            action="get_login_status",
            payload={"bot_key": bot_key},
            timeout=10.0,
            bot_key=bot_key or None,
            worker_type="ilink",
        )
        return result
    except Exception as e:
        logger.error(f"查询 iLink 登录状态失败: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


@router.get("/ilink/activated_users")
async def ilink_activated_users(bot_key: str = Query("", description="ilink worker 的 bot_key")):
    """列出 iLink 已激活用户。"""
    engine = _ilink_engine(bot_key)
    if engine:
        return await engine.list_activated_users()
    try:
        result = await ws_manager.send_request(
            action="list_activated_users",
            payload={"bot_key": bot_key},
            timeout=10.0,
            bot_key=bot_key or None,
            worker_type="ilink",
        )
        return result
    except Exception as e:
        logger.error(f"查询 iLink 已激活用户失败: {e}", exc_info=True)
        return {"status": "error", "error": str(e), "users": []}


# ============== 动态引擎注册（普通用户：Cursor 配置带凭证，MCP 启动时自举后端引擎）==============


class WecomAibotStartRequest(BaseModel):
    bot_id: str
    bot_secret: str
    bot_key: str = "wecom-aibot-1"


@router.post("/engines/wecom-aibot/start")
async def engines_wecom_aibot_start(request: WecomAibotStartRequest):
    """运行时启动企微 AI Bot 内置引擎（无需重启 HITL Server）。

    由 MCP 端在启动时调用，把用户在 Cursor 配置里填的 bot_id/bot_secret 注册到后端。
    幂等：同 bot_key 同凭证已运行则 no-op；凭证变化则停旧起新。
    """
    from ..engines import engine_manager, WecomAibotEngine
    if not request.bot_id or not request.bot_secret:
        return {"success": False, "error": "需要 bot_id 和 bot_secret"}

    existing = engine_manager.get_by_bot_key(request.bot_key)
    if (
        existing
        and isinstance(existing, WecomAibotEngine)
        and existing.bot_id == request.bot_id
        and existing.bot_secret == request.bot_secret
    ):
        return {"success": True, "status": "already_running"}

    if existing:
        try:
            await existing.stop()
        except Exception:
            pass
        engine_manager.remove(request.bot_key)

    engine = WecomAibotEngine(
        bot_key=request.bot_key,
        bot_id=request.bot_id,
        bot_secret=request.bot_secret,
        ws_url=config.wecom_aibot_ws_url,
        heartbeat_interval=config.wecom_aibot_heartbeat_interval,
        reconnect_delay=config.wecom_aibot_reconnect_delay,
    )
    engine.on_user_message = storage.handle_callback
    engine_manager.register(engine)
    try:
        await engine.start()
    except Exception as e:
        engine_manager.remove(request.bot_key)
        logger.error(f"启动 wecom-aibot 引擎失败: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
    logger.info(f"动态启动 wecom-aibot 引擎: bot_key={request.bot_key}, bot_id={request.bot_id}")
    return {"success": True, "status": "started"}
