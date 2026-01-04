"""
消息发送器

调用 fly-pigeon 发送消息到企业微信
这是一个纯代理模块，不做会话管理
"""
import base64
import logging

from pigeon import Bot

from .config import config

logger = logging.getLogger(__name__)


def format_message_with_header(message: str, short_id: str, project_name: str | None = None) -> str:
    """
    在消息前添加会话标识头
    
    格式: [#short_id 项目名] 消息内容
    """
    if project_name:
        header = f"[#{short_id} {project_name}]"
    else:
        header = f"[#{short_id}]"
    return f"{header}\n{message}"


def send_to_wecom(
    message: str,
    chat_id: str | None = None,
    bot_key: str | None = None,
    msg_type: str = "text",
    images: list[str] | None = None,
) -> dict:
    """
    使用 fly-pigeon 库发送消息到企业微信
    """
    bot_key = bot_key or config.bot_key
    
    if not bot_key:
        raise ValueError("未配置 bot_key")
    
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
            image_content = images[0]
            # 如果是 data URL 格式，提取纯 base64 部分
            if image_content.startswith("data:"):
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
        
        # 记录响应内容
        response_data = None
        if hasattr(result, 'json'):
            try:
                response_data = result.json()
            except Exception:
                pass
        elif isinstance(result, dict):
            response_data = result
        
        logger.info(f"fly-pigeon 响应: status={result}, data={response_data}")
        
        # 检查是否真的发送成功
        if response_data:
            errcode = response_data.get("errcode", 0)
            if errcode != 0:
                logger.error(f"企微发送失败: errcode={errcode}, errmsg={response_data.get('errmsg')}")
                return response_data
        
        return response_data or {"errcode": 0, "errmsg": "ok"}
        
    except Exception as e:
        logger.error(f"fly-pigeon 发送失败: {e}", exc_info=True)
        raise


async def handle_send_message(payload: dict) -> dict:
    """
    处理发送消息请求（纯代理，不做会话管理）
    
    Args:
        payload: 请求参数（由 Relay Server 传入）
            - short_id: 会话短 ID（由 Relay 生成）
            - message: 消息内容
            - chat_id: 群/私聊 ID
            - images: 图片列表
            - project_name: 项目名称
    
    Returns:
        { success: bool, error?: str }
    """
    short_id = payload.get("short_id")
    message = payload.get("message", "")
    chat_id = payload.get("chat_id")
    images = payload.get("images")
    project_name = payload.get("project_name")
    
    if not chat_id:
        return {"success": False, "error": "未指定 chat_id"}
    
    if not short_id:
        return {"success": False, "error": "未指定 short_id"}
    
    try:
        # 添加会话标识头
        formatted_message = format_message_with_header(
            message,
            short_id,
            project_name
        )
        
        # 发送文本消息
        result = send_to_wecom(
            message=formatted_message,
            chat_id=chat_id
        )
        
        # 检查发送结果
        if isinstance(result, dict) and result.get("errcode", 0) != 0:
            return {
                "success": False,
                "error": f"发送失败: {result.get('errmsg', '未知错误')}"
            }
        
        # 发送图片
        if images:
            for image_url in images:
                try:
                    send_to_wecom(
                        message="",
                        chat_id=chat_id,
                        msg_type="image",
                        images=[image_url]
                    )
                except Exception as e:
                    logger.warning(f"发送图片失败: {image_url}, {e}")
        
        return {"success": True}
        
    except Exception as e:
        logger.error(f"发送消息失败: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


async def handle_upload_image(payload: dict) -> dict:
    """
    处理上传图片请求
    
    Args:
        payload: 请求参数
            - content: base64 编码的图片内容
            - content_type: MIME 类型
    
    Returns:
        { image_url: str }
    """
    content = payload.get("content", "")
    content_type = payload.get("content_type", "image/png")
    
    # 构造 data URL
    data_url = f"data:{content_type};base64,{content}"
    
    return {"image_url": data_url}


async def handle_send_hint(payload: dict) -> dict:
    """
    处理发送提示消息请求（如 Chat ID 提示）
    
    Args:
        payload: 请求参数
            - chat_id: 群/私聊 ID
            - message: 提示消息内容
            - msg_type: 消息类型（text/markdown）
    
    Returns:
        { success: bool, error?: str }
    """
    chat_id = payload.get("chat_id")
    message = payload.get("message", "")
    msg_type = payload.get("msg_type", "markdown")
    
    if not chat_id:
        return {"success": False, "error": "未指定 chat_id"}
    
    try:
        send_to_wecom(
            message=message,
            chat_id=chat_id,
            msg_type=msg_type
        )
        return {"success": True}
        
    except Exception as e:
        logger.error(f"发送提示消息失败: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
