"""
发送消息处理器
"""
import base64
import logging
import httpx
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from pydantic import BaseModel
from typing import Any

from pigeon import Bot

from ..storage import storage
from ..config import config

logger = logging.getLogger(__name__)
router = APIRouter()


class SendMessageRequest(BaseModel):
    """发送消息请求"""
    message: str
    chat_id: str | None = None  # 群 ID 或 个人会话 ID
    user_id: str | None = None  # 私聊用户 ID
    chat_type: str = "group"  # group 或 single
    images: list[str] | None = None  # 图片 URL 列表（已上传到某处的 URL）
    mention_list: list[str] | None = None  # @的用户列表
    project_name: str | None = None  # 项目名称，用于标识消息来源
    timeout: int | None = None  # 会话超时时间（秒），由 MCP 传入，两边保持一致


class SendMessageResponse(BaseModel):
    """发送消息响应"""
    success: bool
    session_id: str | None = None
    message: str = ""
    error: str | None = None


class UploadImageResponse(BaseModel):
    """上传图片响应"""
    success: bool
    image_url: str | None = None
    error: str | None = None


def send_to_wecom(
    message: str,
    chat_id: str | None = None,
    bot_key: str | None = None,
    msg_type: str = "text",
    images: list[str] | None = None,
    mention_list: list[str] | None = None,
) -> dict:
    """
    使用 fly-pigeon 库发送消息到企业微信
    
    支持发送到群聊和私聊
    """
    bot_key = bot_key or config.bot_key
    
    if not bot_key:
        raise ValueError("未配置 bot_key")
    
    # 创建 Bot 实例
    bot = Bot(bot_key=bot_key)
    
    logger.info(f"发送消息到企微: chat_id={chat_id}, msg_type={msg_type}, message={message[:50]}...")
    
    try:
        if msg_type == "text":
            result = bot.text(
                chat_id=chat_id,
                msg_content=message,
            )
        elif msg_type == "markdown":
            result = bot.markdown(
                chat_id=chat_id,
                msg_content=message,
            )
        elif msg_type == "image" and images:
            # fly-pigeon 支持: 本地文件路径、base64 字符串、在线 URL
            image_content = images[0]
            # 如果是 data URL 格式，提取纯 base64 部分
            if image_content.startswith("data:"):
                # 格式: data:image/png;base64,xxxxx
                image_content = image_content.split(",", 1)[1] if "," in image_content else image_content
            
            result = bot.image(
                msg_content=image_content,
                chat_id=chat_id,
            )
        else:
            result = bot.text(
                chat_id=chat_id,
                msg_content=message,
            )
        
        logger.info(f"fly-pigeon 响应: {result}")
        return result or {"errcode": 0, "errmsg": "ok"}
        
    except Exception as e:
        logger.error(f"fly-pigeon 发送失败: {e}", exc_info=True)
        raise


def format_message_with_header(message: str, short_id: str, project_name: str | None = None) -> str:
    """
    在消息前添加会话标识头
    
    格式: [#short_id 项目名] 消息内容
    
    这个标识会在用户引用回复时被一起引用，从而实现会话匹配
    """
    if project_name:
        header = f"[#{short_id} {project_name}]"
    else:
        header = f"[#{short_id}]"
    return f"{header}\n{message}"


@router.post("/send", response_model=SendMessageResponse)
async def send_message(request: SendMessageRequest):
    """
    发送消息并创建会话
    """
    try:
        chat_id = request.chat_id
        logger.info(f"收到发送请求: project_name={request.project_name}, chat_id={chat_id}")
        
        if not chat_id:
            return SendMessageResponse(
                success=False,
                error="未指定 chat_id 且未配置默认值"
            )
        
        # 先创建会话以获取 short_id
        session = await storage.create_session(
            chat_id=chat_id,
            chat_type=request.chat_type,
            message=request.message,
            images=request.images,
            project_name=request.project_name or "",
            timeout=request.timeout  # 由 MCP 传入的超时时间
        )
        
        # 在消息中添加会话标识头
        formatted_message = format_message_with_header(
            request.message,
            session.short_id,
            request.project_name
        )
        
        # 发送文本消息（使用 fly-pigeon）
        send_to_wecom(
            message=formatted_message,
            chat_id=chat_id,
            mention_list=request.mention_list
        )
        
        # 如果有图片，也发送图片（fly-pigeon 支持图片 URL）
        if request.images:
            for image_url in request.images:
                try:
                    send_to_wecom(
                        message="",
                        chat_id=chat_id,
                        msg_type="image",
                        images=[image_url]
                    )
                except Exception as e:
                    logger.warning(f"发送图片失败: {image_url}, {e}")
        
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


@router.post("/upload-image", response_model=UploadImageResponse)
async def upload_image(
    file: UploadFile = File(...),
):
    """
    上传图片
    
    MCP Server 会将本地图片文件上传到这里，
    然后返回可以在企微中使用的 URL
    """
    try:
        # 读取图片内容
        content = await file.read()
        
        # 方案1: 上传到飞鸽/企微获取临时 URL
        # 方案2: 保存到本地并提供访问 URL
        # 方案3: 上传到对象存储
        
        # 这里先使用 base64 编码（飞鸽支持 base64 图片）
        b64_content = base64.b64encode(content).decode("utf-8")
        
        # 获取 MIME 类型
        content_type = file.content_type or "image/png"
        
        # 构造 data URL
        data_url = f"data:{content_type};base64,{b64_content}"
        
        # 如果图片太大，可能需要先上传到飞鸽获取 URL
        # 这里简单返回 base64 URL
        return UploadImageResponse(
            success=True,
            image_url=data_url
        )
        
    except Exception as e:
        logger.error(f"上传图片失败: {e}", exc_info=True)
        return UploadImageResponse(
            success=False,
            error=str(e)
        )
