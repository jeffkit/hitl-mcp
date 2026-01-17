"""
消息转发服务

将用户消息转发到 Agent 并处理响应
"""
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple

import httpx

from ..config import config
from ..database import get_db_manager
from ..repository import get_user_project_repository

logger = logging.getLogger(__name__)


@dataclass
class AgentResult:
    """Agent 响应结果（包含 session_id）"""
    reply: str
    msg_type: str = "text"
    session_id: str | None = None
    project_id: str | None = None  # 新增：使用的项目 ID
    project_name: str | None = None  # 新增：项目名称


@dataclass
class ForwardConfig:
    """转发配置"""
    url_template: str
    api_key: str | None
    timeout: int
    project_id: str | None = None
    project_name: str | None = None

    def get_url(self) -> str:
        """获取完整 URL"""
        return self.url_template


async def get_forward_config_for_user(
    bot_key: str,
    chat_id: str,
    current_project_id: str | None = None
) -> ForwardConfig:
    """
    获取用户的转发配置（优先级：用户项目 > Bot 默认配置）

    Args:
        bot_key: Bot Key
        chat_id: 用户/群 ID
        current_project_id: 当前会话指定的项目 ID（可选）

    Returns:
        ForwardConfig 对象
    """
    try:
        db_manager = get_db_manager()
        async with db_manager.get_session() as session:
            project_repo = get_user_project_repository(session)

            # 1. 如果会话指定了项目，优先使用会话的项目
            if current_project_id:
                project = await project_repo.get_by_project_id(bot_key, chat_id, current_project_id)
                if project and project.enabled:
                    logger.info(f"使用会话项目配置: {current_project_id}")
                    return ForwardConfig(
                        url_template=project.url_template,
                        api_key=project.api_key,
                        timeout=project.timeout,
                        project_id=project.project_id,
                        project_name=project.project_name
                    )

            # 2. 查询用户的默认项目
            default_project = await project_repo.get_default_project(bot_key, chat_id)
            if default_project:
                logger.info(f"使用用户默认项目: {default_project.project_id}")
                return ForwardConfig(
                    url_template=default_project.url_template,
                    api_key=default_project.api_key,
                    timeout=default_project.timeout,
                    project_id=default_project.project_id,
                    project_name=default_project.project_name
                )

    except Exception as e:
        logger.error(f"获取用户项目配置失败: {e}，回退到 Bot 配置")

    # 3. 兜底：使用 Bot 级别配置
    bot = await config.get_bot_or_default_from_db(bot_key)
    if not bot:
        logger.warning(f"未找到 Bot 配置: bot_key={bot_key}")
        raise ValueError(f"未找到 Bot 配置: bot_key={bot_key}")

    logger.info(f"使用 Bot 默认配置: {bot.name}")
    return ForwardConfig(
        url_template=bot.forward_config.target_url,
        api_key=bot.forward_config.api_key,
        timeout=bot.forward_config.timeout,
        project_id=None,
        project_name=None
    )


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
    # 获取 Bot 配置（从数据库实时读取，确保多进程一致性）
    bot = await config.get_bot_or_default_from_db(bot_key)
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
    
    logger.info(f"转发消息到 Agent: url={target_url}, session_id={session_id[:8] if session_id else 'None'}, timeout={bot_timeout}s")
    
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
    
    # 生成请求 ID 用于追踪
    import uuid
    request_id = str(uuid.uuid4())[:8]
    
    try:
        # 设置更合理的超时配置：
        # - connect: 30秒（建立连接的超时）
        # - read: bot_timeout（等待响应的超时，Agent 处理可能很慢）
        # - write: 30秒（发送请求的超时）
        # - pool: 30秒（从连接池获取连接的超时）
        timeout_config = httpx.Timeout(
            connect=30.0,
            read=float(bot_timeout),
            write=30.0,
            pool=30.0
        )
        
        logger.debug(f"[{request_id}] 准备创建 httpx.AsyncClient, read_timeout={bot_timeout}s")
        
        # 添加事件钩子来追踪请求状态
        async def log_request(request):
            logger.debug(f"[{request_id}] >> HTTP 请求开始: {request.method} {request.url}")
            logger.debug(f"[{request_id}] >> Headers: {dict(request.headers)}")
        
        async def log_response(response):
            logger.debug(f"[{request_id}] << HTTP 响应: {response.status_code}")
        
        async with httpx.AsyncClient(
            timeout=timeout_config,
            event_hooks={'request': [log_request], 'response': [log_response]}
        ) as client:
            logger.debug(f"[{request_id}] httpx.AsyncClient 已创建，开始 POST 请求到 {target_url}")
            logger.debug(f"[{request_id}] 请求体: {request_body}")
            response = await client.post(
                target_url,
                json=request_body,
                headers=headers
            )
            logger.debug(f"[{request_id}] POST 请求完成，状态码: {response.status_code}")
            
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
            
    except httpx.TimeoutException as e:
        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
        logger.error(f"[{request_id}] 转发请求超时: {target_url}, 耗时: {duration_ms}ms, 错误类型: {type(e).__name__}")
        return AgentResult(
            reply="⚠️ 请求超时，Agent 响应时间过长",
            msg_type="text"
        )
    except Exception as e:
        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
        logger.error(f"[{request_id}] 转发请求失败: {e}, 耗时: {duration_ms}ms", exc_info=True)
        return AgentResult(
            reply=f"⚠️ 请求失败: {str(e)}",
            msg_type="text"
        )


async def forward_to_agent_with_user_project(
    bot_key: str | None,
    chat_id: str,
    content: str,
    timeout: int,
    session_id: str | None = None,
    current_project_id: str | None = None
) -> AgentResult | None:
    """
    使用用户项目配置转发消息到 Agent（支持三层架构）

    优先级：用户项目配置 > Bot 默认配置

    Args:
        bot_key: Bot Key
        chat_id: 用户/群 ID
        content: 消息内容
        timeout: 超时时间（秒）
        session_id: 会话 ID（可选）
        current_project_id: 当前会话指定的项目 ID（可选）

    Returns:
        AgentResult 或 None（包含项目信息）
    """
    # 获取用户的转发配置（自动选择优先级）
    forward_config = await get_forward_config_for_user(bot_key, chat_id, current_project_id)

    # 获取目标 URL
    target_url = forward_config.get_url()
    if not target_url:
        logger.warning(f"转发配置的 URL 为空")
        return None

    # 获取 API Key 和超时配置
    api_key = forward_config.api_key
    request_timeout = forward_config.timeout or timeout

    logger.info(
        f"转发消息到 Agent: url={target_url}, "
        f"project={forward_config.project_id or 'Bot默认'}, "
        f"session_id={session_id[:8] if session_id else 'None'}, "
        f"timeout={request_timeout}s"
    )

    # 构建请求头
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # 构建请求体（AgentStudio 格式）
    request_body = {"message": content}
    if session_id:
        request_body["sessionId"] = session_id

    start_time = datetime.now()

    # 生成请求 ID 用于追踪
    import uuid
    request_id = str(uuid.uuid4())[:8]

    try:
        # 设置超时配置
        timeout_config = httpx.Timeout(
            connect=30.0,
            read=float(request_timeout),
            write=30.0,
            pool=30.0
        )

        logger.debug(f"[{request_id}] 准备创建 httpx.AsyncClient, read_timeout={request_timeout}s")

        # 添加事件钩子来追踪请求状态
        async def log_request(request):
            logger.debug(f"[{request_id}] >> HTTP 请求开始: {request.method} {request.url}")
            logger.debug(f"[{request_id}] >> Headers: {dict(request.headers)}")

        async def log_response(response):
            logger.debug(f"[{request_id}] << HTTP 响应: {response.status_code}")

        async with httpx.AsyncClient(
            timeout=timeout_config,
            event_hooks={'request': [log_request], 'response': [log_response]}
        ) as client:
            logger.debug(f"[{request_id}] httpx.AsyncClient 已创建，开始 POST 请求到 {target_url}")
            logger.debug(f"[{request_id}] 请求体: {request_body}")
            response = await client.post(
                target_url,
                json=request_body,
                headers=headers
            )
            logger.debug(f"[{request_id}] POST 请求完成，状态码: {response.status_code}")

            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

            if response.status_code != 200:
                logger.error(f"Agent 返回错误: status={response.status_code}, body={response.text[:200]}")
                return AgentResult(
                    reply=f"⚠️ Agent 返回错误\n状态码: {response.status_code}\n响应: {response.text[:200]}",
                    msg_type="text",
                    project_id=forward_config.project_id,
                    project_name=forward_config.project_name
                )

            # 解析响应
            try:
                result = response.json()
            except Exception as e:
                logger.warning(f"解析 JSON 响应失败: {e}，使用原始文本")
                return AgentResult(
                    reply=response.text[:1000],
                    msg_type="text",
                    session_id=session_id,
                    project_id=forward_config.project_id,
                    project_name=forward_config.project_name
                )

            logger.debug(f"[{request_id}] 响应 JSON: {result}")

            # 提取字段（兼容多种格式）
            reply = result.get("reply") or result.get("response") or result.get("message", "")
            response_session_id = result.get("sessionId") or result.get("session_id") or session_id

            if reply:
                return AgentResult(
                    reply=str(reply)[:2000],  # 限制长度
                    msg_type="text",
                    session_id=response_session_id,
                    project_id=forward_config.project_id,
                    project_name=forward_config.project_name
                )

            # 兼容其他格式
            if "data" in result or "json" in result:
                raw_data = result.get("json") or result.get("data", {})
                return AgentResult(
                    reply=f"✅ 消息已处理\n\n响应数据:\n```\n{raw_data}\n```",
                    msg_type="text",
                    session_id=response_session_id,
                    project_id=forward_config.project_id,
                    project_name=forward_config.project_name
                )

            # 默认返回原始响应
            import json as json_module
            return AgentResult(
                reply=f"✅ Agent 响应:\n```\n{json_module.dumps(result, ensure_ascii=False, indent=2)[:500]}\n```",
                msg_type="text",
                session_id=response_session_id,
                project_id=forward_config.project_id,
                project_name=forward_config.project_name
            )

    except httpx.TimeoutException as e:
        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
        logger.error(f"[{request_id}] 转发请求超时: {target_url}, 耗时: {duration_ms}ms, 错误类型: {type(e).__name__}")
        return AgentResult(
            reply="⚠️ 请求超时，Agent 响应时间过长",
            msg_type="text",
            project_id=forward_config.project_id,
            project_name=forward_config.project_name
        )
    except Exception as e:
        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
        logger.error(f"[{request_id}] 转发请求失败: {e}, 耗时: {duration_ms}ms", exc_info=True)
        return AgentResult(
            reply=f"⚠️ 请求失败: {str(e)}",
            msg_type="text",
            project_id=forward_config.project_id,
            project_name=forward_config.project_name
        )
