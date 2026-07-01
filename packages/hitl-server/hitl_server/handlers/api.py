"""
HTTP API 处理器

提供给 MCP Server 调用的 HTTP 接口。
消息收发由内置引擎（ilink / wecom-aibot）在进程内完成。
"""
import logging
from fastapi import APIRouter, UploadFile, File, Query
from pydantic import BaseModel

from ..config import config
from ..storage import storage

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
    upstream: str | None = None       # 指定上游类型：ilink | wecom-aibot（冗余校验）


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


# ============== API 接口 ==============

@router.get("/health", response_model=HealthResponse)
async def health_check():
    """健康检查"""
    return HealthResponse(status="healthy")


@router.post("/send", response_model=SendMessageResponse)
async def send_message(request: SendMessageRequest):
    """发送消息——命中内置引擎则进程内调用，否则报引擎未启动。"""
    from ..engines import engine_manager
    _engine = engine_manager.get_by_bot_key(request.bot_key or "") or (
        engine_manager.get_by_type(request.upstream) if request.upstream else None
    )

    if not _engine:
        upstream = request.upstream or "ilink/wecom-aibot"
        return SendMessageResponse(
            success=False,
            error=f"engine_not_started: {upstream} 引擎未启动，请在管理台初始化"
        )

    try:
        timeout = request.timeout or 300
        session = None
        short_id = ""

        # 查询 chat_type（从数据库）
        chat_type = request.chat_type
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
                chat_type=chat_type,
                message=request.message,
                project_name=request.project_name or "",
                images=request.images,
                timeout=timeout
            )
            short_id = session.short_id
            logger.info(f"创建会话: session_id={session.session_id}, short_id={short_id}")
        else:
            logger.info(f"仅发送消息（不等待回复）: chat_id={request.chat_id}")

        # 2. 内置引擎进程内发送
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

        if not result.get("success", True):
            if session:
                await storage.mark_timeout(session.session_id)
            return SendMessageResponse(
                success=False,
                error=result.get("error", "发送失败")
            )

        # 引擎在未指定 chat_id 时解析出实际收件人后回传 chat_id，
        # 据此更新 session.chat_id，使后续用户回复能按 chat_id 匹配到会话。
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
    """轮询获取用户回复"""
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


@router.post("/upload-image", response_model=UploadImageResponse)
async def upload_image(file: UploadFile = File(...)):
    """上传图片——转换为 data URL 供消息内嵌。"""
    try:
        content = await file.read()
        import base64
        b64_content = base64.b64encode(content).decode("utf-8")
        content_type = file.content_type or "image/png"
        data_url = f"data:{content_type};base64,{b64_content}"
        return UploadImageResponse(success=True, image_url=data_url)
    except Exception as e:
        logger.error(f"上传图片失败: {e}", exc_info=True)
        return UploadImageResponse(success=False, error=str(e))


# ============== iLink 登录 ==============
# 由内置 ilink 引擎提供（进程内）；引擎未启用时返回 error。


def _ilink_engine(bot_key: str):
    """查找内置 ilink 引擎（按 bot_key 精确匹配，否则取任一 ilink 引擎）。"""
    from ..engines import engine_manager
    return engine_manager.get_by_bot_key(bot_key) or engine_manager.get_by_type("ilink")


@router.get("/ilink/qr")
async def ilink_get_qr(bot_key: str = Query("", description="ilink 引擎的 bot_key")):
    """获取 iLink 扫码二维码（内置 ilink 引擎）。

    返回: { status, qr_url, qr_base64, qrcode_key, error? }
    """
    engine = _ilink_engine(bot_key)
    if not engine:
        return {"status": "error", "error": "iLink 引擎未启动，请在管理台启用（ENABLE_ILINK_ENGINE=true）"}
    try:
        return await engine.get_qr()
    except Exception as e:
        logger.error(f"获取 iLink 二维码失败: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


@router.get("/ilink/login_status")
async def ilink_login_status(bot_key: str = Query("", description="ilink 引擎的 bot_key")):
    """查询 iLink 登录状态（内置 ilink 引擎）。

    返回: { status: "pending" | "success" | "expired" | "not_started" | "error" }
    """
    engine = _ilink_engine(bot_key)
    if not engine:
        return {"status": "error", "error": "iLink 引擎未启动，请在管理台启用（ENABLE_ILINK_ENGINE=true）"}
    try:
        return await engine.get_login_status()
    except Exception as e:
        logger.error(f"查询 iLink 登录状态失败: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


@router.get("/ilink/activated_users")
async def ilink_activated_users(bot_key: str = Query("", description="ilink 引擎的 bot_key")):
    """列出 iLink 已激活用户（内置 ilink 引擎）。"""
    engine = _ilink_engine(bot_key)
    if not engine:
        return {"status": "error", "error": "iLink 引擎未启动，请在管理台启用（ENABLE_ILINK_ENGINE=true）", "users": []}
    try:
        return await engine.list_activated_users()
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
