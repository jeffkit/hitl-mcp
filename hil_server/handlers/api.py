"""
HTTP API 处理器

提供给 MCP Server 调用的 HTTP 接口
支持两种模式：
- relay: 通过 WebSocket 转发给 Worker
- direct: 直接调用 fly-pigeon
"""
import logging
from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel

from ..config import config
from ..ws_manager import ws_manager
from ..storage import storage
from ..sender import send_message_direct

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
        
        # 1. 创建会话
        session = await storage.create_session(
            chat_id=request.chat_id,
            chat_type=request.chat_type,
            message=request.message,
            project_name=request.project_name or "",
            images=request.images,
            timeout=timeout
        )
        
        logger.info(f"创建会话: session_id={session.session_id}, short_id={session.short_id}, mode={config.effective_mode}")
        
        # 2. 根据模式发送消息
        if config.is_direct_mode:
            # Direct 模式：直接调用 fly-pigeon
            result = await send_message_direct(
                short_id=session.short_id,
                message=request.message,
                chat_id=request.chat_id,
                project_name=request.project_name,
                images=request.images,
            )
        else:
            # Relay 模式：通过 WebSocket 转发给 Worker
            payload = {
                "short_id": session.short_id,
                "message": request.message,
                "chat_id": request.chat_id,
                "chat_type": request.chat_type,
                "images": request.images,
                "project_name": request.project_name,
            }
            
            result = await ws_manager.send_request(
                action="send_message",
                payload=payload,
                timeout=min(timeout, 60)
            )
        
        if not result.get("success", True):
            await storage.mark_timeout(session.session_id)
            return SendMessageResponse(
                success=False,
                error=result.get("error", "发送失败")
            )
        
        return SendMessageResponse(
            success=True,
            session_id=session.session_id,
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
        
        # 使用 storage 的回调处理逻辑
        result = await storage.handle_callback(data)
        
        if result.get("success"):
            logger.info(f"回调处理成功: session_id={result.get('session_id')}")
        else:
            logger.warning(f"回调处理: {result.get('error')}")
        
        return {"errcode": 0, "errmsg": "ok"}
        
    except Exception as e:
        logger.error(f"处理回调失败: {e}", exc_info=True)
        return {"errcode": -1, "errmsg": str(e)}


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
