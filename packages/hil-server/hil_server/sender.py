"""
消息发送器

Direct 模式下直接调用 fly-pigeon

功能：
- 消息格式化：添加会话标识头
- 消息分拆：当消息超过 4K 时自动分拆
- 每条分拆的消息都保留会话标识，方便用户回复
"""
import logging

from .config import config
from .message_splitter import split_and_format_message, needs_split

logger = logging.getLogger(__name__)


def format_message_with_header(message: str, short_id: str, project_name: str | None = None, wait_reply: bool = True) -> str:
    """
    格式化消息
    
    - 如果有 short_id，在消息前添加会话标识头: [#short_id 项目名] 消息内容
    - 如果没有 short_id（readonly 消息），不添加头部
    - 如果 wait_reply=True，在消息底部添加「请回复」提示
    """
    formatted_message = message
    
    # 1. 添加会话标识头（仅当有 short_id 时）
    if short_id:
        if project_name:
            header = f"[#{short_id} {project_name}]"
        else:
            header = f"[#{short_id}]"
        formatted_message = f"{header}\n{formatted_message}"
    
    # 2. 添加「请回复」提示（仅当需要回复时）
    if wait_reply:
        formatted_message = f"{formatted_message}\n\n---\n📮 **请回复**"
    
    return formatted_message


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
    from pigeon import Bot
    
    bot_key = bot_key or config.bot_key
    
    if not bot_key:
        raise ValueError("未配置 bot_key")
    
    bot = Bot(bot_key=bot_key)
    
    logger.info(f"[Direct] 发送消息到企微: chat_id={chat_id}, msg_type={msg_type}")
    
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
        
        logger.info(f"[Direct] fly-pigeon 响应: {result}")
        return result or {"errcode": 0, "errmsg": "ok"}
        
    except Exception as e:
        logger.error(f"[Direct] fly-pigeon 发送失败: {e}", exc_info=True)
        raise


async def send_message_direct(
    short_id: str,
    message: str,
    chat_id: str,
    project_name: str | None = None,
    images: list[str] | None = None,
    wait_reply: bool = True,
) -> dict:
    """
    直接发送消息（Direct 模式）
    
    当消息超过 4K 时会自动分拆成多条消息，每条都带有会话标识头。
    
    Args:
        short_id: 会话短 ID（用于消息头部标识）
        message: 消息内容
        chat_id: 目标会话 ID
        project_name: 项目名称（显示在消息头部）
        images: 图片列表（base64 或 URL）
        wait_reply: 是否等待回复（影响消息格式）
    
    Returns:
        { success: bool, error?: str, parts_sent?: int }
    """
    try:
        # 检查是否需要分拆
        if needs_split(message, short_id, project_name, wait_reply):
            # 分拆消息
            split_messages = split_and_format_message(
                message=message,
                short_id=short_id,
                project_name=project_name,
                wait_reply=wait_reply
            )
            
            logger.info(f"消息过长，分拆为 {len(split_messages)} 条")
            
            # 逐条发送
            for split_msg in split_messages:
                send_to_wecom(
                    message=split_msg.content,
                    chat_id=chat_id
                )
            
            parts_sent = len(split_messages)
        else:
            # 不需要分拆，使用原有逻辑
            formatted_message = format_message_with_header(message, short_id, project_name, wait_reply)
            
            send_to_wecom(
                message=formatted_message,
                chat_id=chat_id
            )
            parts_sent = 1
        
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
        
        return {"success": True, "parts_sent": parts_sent}
        
    except Exception as e:
        logger.error(f"发送消息失败: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
