"""
飞鸽传书回调处理器
"""
import logging
import re
from fastapi import APIRouter, Request, Header
from pydantic import BaseModel
from typing import Any

from pigeon import Bot

from ..storage import storage, Reply
from ..config import config

logger = logging.getLogger(__name__)
router = APIRouter()


def send_chat_id_hint(chat_id: str, chat_type: str, from_user: dict) -> None:
    """
    当用户消息未匹配到等待中的会话时，回复告诉用户当前的 chat_id
    
    这样用户可以拿到 chat_id 去配置 MCP
    """
    try:
        bot = Bot(bot_key=config.bot_key)
        
        user_name = from_user.get("name", "用户")
        type_desc = "私聊" if chat_type == "single" else "群聊"
        
        message = f"""👋 你好 {user_name}！

当前没有等待中的会话需要你回复。

如果你想配置 MCP 使用此{type_desc}，请使用以下信息：

📋 **Chat ID**: `{chat_id}`
📌 **会话类型**: {type_desc}

你可以将此 Chat ID 配置到 MCP 的环境变量中：
```
DEFAULT_CHAT_ID={chat_id}
```"""
        
        bot.markdown(chat_id=chat_id, msg_content=message)
        logger.info(f"已发送 chat_id 提示: chat_id={chat_id}")
        
    except Exception as e:
        logger.error(f"发送 chat_id 提示失败: {e}", exc_info=True)


def send_multiple_sessions_hint(chat_id: str, sessions: list, from_user: dict) -> None:
    """
    当同一个 chat_id 有多个等待中的会话时，提示用户使用引用回复
    """
    try:
        from ..storage import Session
        bot = Bot(bot_key=config.bot_key)
        
        user_name = from_user.get("name", "用户")
        
        # 构建会话列表
        session_list = []
        for i, session in enumerate(sessions[:5], 1):  # 最多显示5个
            project_info = f" ({session.project_name})" if session.project_name else ""
            short_msg = session.message[:30] + "..." if len(session.message) > 30 else session.message
            session_list.append(f"{i}. `[#{session.short_id}]`{project_info}: {short_msg}")
        
        sessions_text = "\n".join(session_list)
        
        message = f"""⚠️ {user_name}，检测到 {len(sessions)} 个等待回复的消息：

{sessions_text}

请使用「**引用回复**」功能选择要回复的消息，这样我才能准确匹配！

（长按或右键消息 → 选择"引用"或"回复"）"""
        
        bot.markdown(chat_id=chat_id, msg_content=message)
        logger.info(f"已发送多会话提示: chat_id={chat_id}, count={len(sessions)}")
        
    except Exception as e:
        logger.error(f"发送多会话提示失败: {e}", exc_info=True)

# 匹配消息中的会话标识 [#short_id] 或 [#short_id 项目名]
SESSION_ID_PATTERN = re.compile(r'\[#([a-f0-9]{8})(?:\s+[^\]]+)?\]')


def parse_quoted_message(content: str) -> tuple[str | None, str]:
    """
    解析引用消息，提取 short_id 和实际回复内容
    
    企业微信引用消息格式:
    "发送者名称：
    被引用的消息内容..."
    ------
    @机器人 用户的实际回复
    
    Returns:
        (short_id, actual_reply): short_id 可能为 None（非引用消息或未找到标识）
    """
    # 检查是否包含引用格式（中文引号开头 + 分隔线）
    # Unicode 中文引号: 左双引号 U+201C ("), 右双引号 U+201D (")
    left_quote = '\u201c'  # "
    right_quote = '\u201d'  # "
    if not (content.startswith(left_quote) or content.startswith(right_quote)):
        # 不是引用消息，返回原内容
        return None, content
    
    # 查找分隔线
    separator = "------"
    if separator not in content:
        return None, content
    
    # 分割引用部分和回复部分
    parts = content.split(separator, 1)
    quoted_part = parts[0]
    reply_part = parts[1].strip() if len(parts) > 1 else ""
    
    # 从引用部分提取 short_id
    match = SESSION_ID_PATTERN.search(quoted_part)
    short_id = match.group(1) if match else None
    
    # 清理回复部分（去除 @机器人）
    if reply_part.startswith("@"):
        # 去除 @xxx 前缀
        space_idx = reply_part.find(" ")
        if space_idx > 0:
            reply_part = reply_part[space_idx + 1:].strip()
    
    logger.info(f"解析引用消息: short_id={short_id}, reply={reply_part[:50]}...")
    return short_id, reply_part


class CallbackResponse(BaseModel):
    """回调响应"""
    errcode: int = 0
    errmsg: str = "ok"


def extract_reply_from_callback(data: dict) -> tuple[Reply, str | None]:
    """
    从飞鸽回调数据中提取回复信息
    
    飞鸽 v2.0 JSON 格式示例：
    {
        "from": {
            "userid": "xxx",
            "name": "张三",
            "alias": "zhangsan"
        },
        "chatid": "wrkSFfCgAAxxxxxx",
        "chattype": "group",  # 或 "single"
        "msgtype": "text",
        "text": {
            "content": "@机器人 回复内容"
        }
    }
    
    Returns:
        (Reply, short_id): short_id 可能为 None（非引用消息或未找到标识）
    """
    msg_type = data.get("msgtype", "text")
    from_user = data.get("from", {})
    
    content = None
    image_url = None
    short_id = None  # 从引用消息中提取的 short_id
    
    if msg_type == "text":
        text_data = data.get("text", {})
        raw_content = text_data.get("content", "")
        
        # 尝试解析引用消息
        short_id, content = parse_quoted_message(raw_content)
        
        # 如果不是引用消息，按原来的方式处理
        if short_id is None and content == raw_content:
            # 去除 @机器人 的前缀
            if content.startswith("@"):
                parts = content.split(" ", 1)
                if len(parts) > 1:
                    content = parts[1].strip()
    
    elif msg_type == "image":
        image_data = data.get("image", {})
        image_url = image_data.get("image_url", "")
    
    elif msg_type == "mixed":
        # 混合消息
        mixed = data.get("mixed_message", {})
        msg_items = mixed.get("msg_item", [])
        
        contents = []
        images = []
        
        for item in msg_items:
            item_type = item.get("msg_type", "")
            if item_type == "text":
                text = item.get("text", {}).get("content", "")
                # 尝试解析引用消息
                item_short_id, parsed_text = parse_quoted_message(text)
                if item_short_id:
                    short_id = item_short_id
                    text = parsed_text
                elif text.startswith("@"):
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
        image_url = images[0] if images else None  # TODO: 支持多图片
    
    reply = Reply(
        msg_type=msg_type,
        content=content,
        image_url=image_url,
        from_user=from_user,
        raw_data=data
    )
    
    return reply, short_id


@router.post("/callback", response_model=CallbackResponse)
async def handle_callback(
    request: Request,
    x_api_key: str | None = Header(None, alias="x-api-key"),
    authorization: str | None = Header(None)
):
    """
    处理飞鸽传书的回调
    
    飞鸽会将用户的回复消息 POST 到这个接口
    
    匹配策略（优先级从高到低）：
    1. 如果用户使用引用回复，从引用内容中提取 short_id 进行精确匹配
    2. 如果没有引用，则按 chat_id 匹配（向后兼容）
    """
    # 验证鉴权（如果配置了）
    if config.callback_auth_key and config.callback_auth_value:
        expected_auth = f"{config.callback_auth_key}:{config.callback_auth_value}"
        # 检查 x-api-key 或自定义 header
        if x_api_key != config.callback_auth_value:
            logger.warning(f"回调鉴权失败: x_api_key={x_api_key}")
            # 不返回错误，避免飞鸽重试
    
    try:
        data = await request.json()
        logger.info(f"收到飞鸽回调: {data}")
        
        # 提取关键信息
        chat_id = data.get("chatid", "")
        chat_type = data.get("chattype", "group")
        msg_type = data.get("msgtype", "")
        
        # 忽略某些事件类型
        if msg_type in ("event", "enter_chat"):
            logger.info(f"忽略事件类型: {msg_type}")
            return CallbackResponse()
        
        # 提取回复（现在会返回 short_id）
        reply, short_id = extract_reply_from_callback(data)
        logger.info(f"提取回复结果: short_id={short_id}, content={reply.content[:50] if reply.content else None}...")
        
        success = False
        match_method = None
        
        # 优先使用 short_id 匹配（引用消息）
        if short_id:
            success = await storage.add_reply_by_short_id(short_id, reply)
            if success:
                match_method = f"short_id={short_id}"
        
        # 如果 short_id 匹配失败，回退到 chat_id 匹配
        if not success:
            success = await storage.add_reply_by_chat_id(chat_id, reply)
            if success:
                match_method = f"chat_id={chat_id}"
        
        if success:
            logger.info(f"成功添加回复到会话: {match_method}")
        else:
            # 未匹配到会话，检查是否有多个等待中的会话
            from_user = data.get("from", {})
            waiting_sessions = await storage.get_waiting_sessions_by_chat_id(chat_id)
            
            if len(waiting_sessions) > 1:
                # 有多个等待中的会话，提示用户使用引用回复
                logger.warning(f"检测到多个等待中的会话: chat_id={chat_id}, count={len(waiting_sessions)}")
                send_multiple_sessions_hint(chat_id, waiting_sessions, from_user)
            elif len(waiting_sessions) == 0:
                # 没有等待中的会话，回复用户告诉他 chat_id
                logger.warning(f"未找到等待中的会话: short_id={short_id}, chat_id={chat_id}")
                send_chat_id_hint(chat_id, chat_type, from_user)
            else:
                # 只有一个等待中的会话，但匹配失败了（不应该发生）
                logger.error(f"匹配逻辑异常: 有1个等待会话但匹配失败, chat_id={chat_id}")
        
        return CallbackResponse()
        
    except Exception as e:
        logger.error(f"处理回调失败: {e}", exc_info=True)
        return CallbackResponse(errcode=-1, errmsg=str(e))
