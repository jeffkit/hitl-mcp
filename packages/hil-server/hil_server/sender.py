"""
消息发送器

Direct 模式下直接调用 fly-pigeon

功能：
- 消息格式化：添加会话标识头
- 消息分拆：当消息超过 4K 时自动分拆（群聊）
- 单聊截断：超过 4K 时截断消息并生成文件链接
- 每条分拆的消息都保留会话标识，方便用户回复
"""
import logging

from .config import config
from .message_splitter import (
    split_and_format_message, 
    needs_split, 
    get_string_bytes,
    MAX_MESSAGE_BYTES
)
from .file_storage import get_file_storage

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
    
    logger.info(f"[Direct] 发送消息到企微: chat_id={chat_id}, msg_type={msg_type}, message_len={len(message)}")
    
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
        
        # 详细记录 fly-pigeon 响应
        logger.info(f"[Direct] fly-pigeon 响应: {result}")
        
        # 提取响应内容（fly-pigeon 返回的是 Response 对象）
        response_data = {}
        if hasattr(result, 'json'):
            try:
                response_data = result.json() if callable(result.json) else result.json
            except Exception:
                response_data = {"errcode": 0, "errmsg": "ok"}
        elif isinstance(result, dict):
            response_data = result
        else:
            response_data = {"errcode": 0, "errmsg": "ok"}
        
        # 检查是否有错误码
        errcode = response_data.get("errcode", 0)
        errmsg = response_data.get("errmsg", "")
        
        if errcode != 0:
            logger.error(f"[Direct] ⚠️  fly-pigeon 返回错误: errcode={errcode}, errmsg={errmsg}, chat_id={chat_id}")
        
        return response_data
        
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
    chat_type: str = "group",
) -> dict:
    """
    直接发送消息（Direct 模式）
    
    根据 chat_type 采用不同的处理策略：
    - 群聊 (group)：超过 4K 时分拆成多条消息
    - 单聊 (single)：超过 4K 时截断并生成文件链接
    
    Args:
        short_id: 会话短 ID（用于消息头部标识）
        message: 消息内容
        chat_id: 目标会话 ID
        project_name: 项目名称（显示在消息头部）
        images: 图片列表（base64 或 URL）
        wait_reply: 是否等待回复（影响消息格式）
        chat_type: 会话类型 (group/single)
    
    Returns:
        { success: bool, error?: str, parts_sent?: int, file_url?: str }
    """
    try:
        # 检查是否需要分拆（消息超过限制）
        if needs_split(message, short_id, project_name, wait_reply):
            # 无论单聊还是群聊，都使用分拆策略
            result = await _send_group_chat_split(
                message=message,
                short_id=short_id,
                project_name=project_name,
                chat_id=chat_id,
                wait_reply=wait_reply
            )
        else:
            # 不需要分拆，使用原有逻辑
            formatted_message = format_message_with_header(message, short_id, project_name, wait_reply)
            
            send_to_wecom(
                message=formatted_message,
                chat_id=chat_id
            )
            result = {"success": True, "parts_sent": 1}
        
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
        
        return result
        
    except Exception as e:
        logger.error(f"发送消息失败: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


async def _send_group_chat_split(
    message: str,
    short_id: str,
    project_name: str | None,
    chat_id: str,
    wait_reply: bool
) -> dict:
    """
    群聊处理：分拆消息成多条发送
    """
    split_messages = split_and_format_message(
        message=message,
        short_id=short_id,
        project_name=project_name,
        wait_reply=wait_reply
    )
    
    logger.info(f"[群聊] 消息过长，分拆为 {len(split_messages)} 条")
    
    # 逐条发送，记录每条的发送结果
    success_count = 0
    fail_count = 0
    
    for i, split_msg in enumerate(split_messages, 1):
        logger.info(f"[群聊] 发送第 {i}/{len(split_messages)} 条，长度：{len(split_msg.content)} 字节")
        
        result = send_to_wecom(
            message=split_msg.content,
            chat_id=chat_id
        )
        
        # 检查发送结果
        if result and isinstance(result, dict):
            errcode = result.get("errcode", 0)
            if errcode == 0:
                success_count += 1
                logger.info(f"[群聊] 第 {i}/{len(split_messages)} 条发送成功")
            else:
                fail_count += 1
                logger.error(f"[群聊] ❌ 第 {i}/{len(split_messages)} 条发送失败: {result}")
    
    logger.info(f"[群聊] 分拆发送完成: 总共 {len(split_messages)} 条, 成功 {success_count} 条, 失败 {fail_count} 条")
    
    return {
        "success": fail_count == 0,
        "parts_sent": len(split_messages),
        "success_count": success_count,
        "fail_count": fail_count
    }


async def _send_single_chat_with_file(
    message: str,
    short_id: str,
    project_name: str | None,
    chat_id: str,
    wait_reply: bool
) -> dict:
    """
    单聊处理：截断消息并生成文件链接
    
    流程：
    1. 保存完整消息为 .md 文件
    2. 计算可用空间
    3. 截断消息内容
    4. 组装：[#short_id 项目名] + 截断内容 + 文件链接
    5. 确保总长度 ≤ 4K
    """
    # 1. 保存完整消息为文件
    file_storage = get_file_storage()
    filename, file_url = file_storage.save_message(
        content=message,
        short_id=short_id,
        project_name=project_name or ""
    )
    
    logger.info(f"[单聊] 消息过长，已保存为文件: {filename}")
    
    # 2. 计算各部分的字节数
    # 构建头部
    if short_id:
        if project_name:
            header = f"[#{short_id} {project_name}]\n"
        else:
            header = f"[#{short_id}]\n"
    else:
        header = ""
    
    # 构建文件链接部分
    link_suffix = f"\n\n---\n📎 **完整内容**: {file_url}"
    
    # 构建回复提示
    reply_suffix = "\n\n---\n📮 **请回复**" if wait_reply else ""
    
    # 计算固定部分的字节数
    header_bytes = get_string_bytes(header)
    link_bytes = get_string_bytes(link_suffix)
    reply_bytes = get_string_bytes(reply_suffix)
    fixed_bytes = header_bytes + link_bytes + reply_bytes
    
    # 3. 计算可用于消息内容的空间
    available_bytes = MAX_MESSAGE_BYTES - fixed_bytes - 50  # 预留 50 字节余量
    
    if available_bytes < 100:
        # 空间太小，直接发送链接
        logger.warning(f"[单聊] 可用空间太小 ({available_bytes} bytes)，只发送链接")
        truncated_content = "（消息内容过长，请点击链接查看）"
    else:
        # 4. 截断消息内容
        truncated_content = _truncate_message(message, available_bytes)
    
    # 5. 组装最终消息
    final_message = f"{header}{truncated_content}{link_suffix}{reply_suffix}"
    
    # 验证最终长度
    final_bytes = get_string_bytes(final_message)
    if final_bytes > MAX_MESSAGE_BYTES:
        logger.error(f"[单聊] 最终消息仍超过限制: {final_bytes} > {MAX_MESSAGE_BYTES}")
        # 强制进一步截断
        overflow = final_bytes - MAX_MESSAGE_BYTES + 50
        truncated_content = _truncate_message(truncated_content, get_string_bytes(truncated_content) - overflow)
        final_message = f"{header}{truncated_content}{link_suffix}{reply_suffix}"
    
    # 发送消息
    send_to_wecom(
        message=final_message,
        chat_id=chat_id
    )
    
    return {"success": True, "parts_sent": 1, "file_url": file_url}


def _truncate_message(message: str, max_bytes: int) -> str:
    """
    截断消息到指定字节数
    
    尽量在换行符或句子边界处截断。
    """
    if get_string_bytes(message) <= max_bytes:
        return message
    
    # 逐字符累积，直到接近限制
    result_chars = []
    current_bytes = 0
    truncate_indicator = "...\n\n（以下内容已截断）"
    indicator_bytes = get_string_bytes(truncate_indicator)
    target_bytes = max_bytes - indicator_bytes
    
    for char in message:
        char_bytes = get_string_bytes(char)
        if current_bytes + char_bytes > target_bytes:
            break
        result_chars.append(char)
        current_bytes += char_bytes
    
    truncated = ''.join(result_chars)
    
    # 尝试在换行符处截断
    last_newline = truncated.rfind('\n')
    if last_newline > len(truncated) * 0.5:  # 如果换行符在后半部分
        truncated = truncated[:last_newline]
    
    return truncated + truncate_indicator
