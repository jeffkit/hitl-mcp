"""
消息转发服务

将用户消息转发到 Agent 并处理响应
"""
import logging
from dataclasses import dataclass
from datetime import datetime

import httpx

from ..config import config

logger = logging.getLogger(__name__)


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
