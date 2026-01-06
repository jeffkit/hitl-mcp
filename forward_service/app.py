"""
Forward Service 主应用

接收企微机器人回调，转发到目标 URL，并将结果返回给用户。
支持多 chat_id 配置，每个 chat_id 可以有独立的 Agent 配置。

运行方式:
    python -m forward_service.app
    # 或
    uvicorn forward_service.app:app --host 0.0.0.0 --port 8083
"""
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from collections import deque
from dataclasses import dataclass, field, asdict

import httpx
from pathlib import Path
from fastapi import FastAPI, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .config import config
from .sender import send_reply

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# ============== 数据模型 ==============

class ForwardRequest(BaseModel):
    """转发给目标 URL 的请求体（通用格式）"""
    chat_id: str
    chat_type: str
    from_user: dict
    msg_type: str
    content: str | None = None
    image_url: str | None = None
    raw_data: dict | None = None


class ForwardResponse(BaseModel):
    """目标 URL 返回的响应体"""
    reply: str
    msg_type: str = "text"  # text / markdown


# ============== 请求日志（用于管理台） ==============

@dataclass
class RequestLog:
    """请求日志"""
    timestamp: str
    chat_id: str
    from_user: str
    content: str
    target_url: str
    status: str  # success / error
    response: str | None = None
    error: str | None = None
    duration_ms: int = 0


# 最近的请求日志（内存存储，保留最近 100 条）
request_logs: deque[RequestLog] = deque(maxlen=100)


def add_request_log(log: RequestLog):
    """添加请求日志"""
    request_logs.appendleft(log)


# ============== 辅助函数 ==============

def extract_content(data: dict) -> tuple[str | None, str | None]:
    """
    从回调数据中提取消息内容
    
    Args:
        data: 飞鸽回调原始数据
    
    Returns:
        (text_content, image_url)
    """
    msg_type = data.get("msgtype", "")
    
    if msg_type == "text":
        text_data = data.get("text", {})
        content = text_data.get("content", "")
        # 去除 @机器人
        if content.startswith("@"):
            parts = content.split(" ", 1)
            if len(parts) > 1:
                content = parts[1].strip()
        return content, None
    
    elif msg_type == "image":
        image_data = data.get("image", {})
        return None, image_data.get("image_url", "")
    
    elif msg_type == "mixed":
        mixed = data.get("mixed_message", {})
        msg_items = mixed.get("msg_item", [])
        
        contents = []
        images = []
        
        for item in msg_items:
            item_type = item.get("msg_type", "")
            if item_type == "text":
                text = item.get("text", {}).get("content", "")
                # 去除 @机器人
                if text.startswith("@"):
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
        image_url = images[0] if images else None
        return content, image_url
    
    return None, None


async def forward_to_agent(
    chat_id: str,
    content: str,
    timeout: int
) -> ForwardResponse | None:
    """
    转发消息到 Agent（适配 AgentStudio API 格式）
    
    Args:
        chat_id: 群/私聊 ID
        content: 消息内容
        timeout: 超时时间（秒）
    
    Returns:
        ForwardResponse 或 None
    """
    # 获取目标 URL
    target_url = config.get_target_url(chat_id)
    if not target_url:
        logger.warning(f"未找到 chat_id={chat_id} 的转发规则")
        return None
    
    # 获取 API Key
    api_key = config.get_api_key(chat_id)
    
    logger.info(f"转发消息到 Agent: url={target_url}")
    
    # 构建请求头
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    
    # 构建请求体（AgentStudio 格式）
    request_body = {"message": content}
    
    start_time = datetime.now()
    
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                target_url,
                json=request_body,
                headers=headers
            )
            
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            
            if response.status_code != 200:
                logger.error(f"Agent 返回错误: status={response.status_code}, body={response.text[:200]}")
                return ForwardResponse(
                    reply=f"⚠️ Agent 返回错误\n状态码: {response.status_code}\n响应: {response.text[:200]}",
                    msg_type="text"
                )
            
            result = response.json()
            logger.info(f"Agent 响应: {str(result)[:200]}")
            
            # 适配 AgentStudio 响应格式: {"response": "..."}
            if "response" in result:
                return ForwardResponse(
                    reply=result["response"],
                    msg_type="text"
                )
            
            # 兼容标准格式: {"reply": "...", "msg_type": "..."}
            if "reply" in result:
                return ForwardResponse(**result)
            
            # 兼容其他格式
            if "data" in result or "json" in result:
                raw_data = result.get("json") or result.get("data", {})
                return ForwardResponse(
                    reply=f"✅ 消息已处理\n\n响应数据:\n```\n{raw_data}\n```",
                    msg_type="text"
                )
            
            # 默认返回原始响应
            import json as json_module
            return ForwardResponse(
                reply=f"✅ Agent 响应:\n```\n{json_module.dumps(result, ensure_ascii=False, indent=2)[:500]}\n```",
                msg_type="text"
            )
            
    except httpx.TimeoutException:
        logger.error(f"转发请求超时: {target_url}")
        return ForwardResponse(
            reply="⚠️ 请求超时，Agent 响应时间过长",
            msg_type="text"
        )
    except Exception as e:
        logger.error(f"转发请求失败: {e}", exc_info=True)
        return ForwardResponse(
            reply=f"⚠️ 请求失败: {str(e)}",
            msg_type="text"
        )


# ============== FastAPI 应用 ==============

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时验证配置
    errors = config.validate()
    if errors:
        for error in errors:
            logger.warning(f"配置警告: {error}")
    
    logger.info(f"Forward Service 启动")
    logger.info(f"  端口: {config.port}")
    logger.info(f"  默认目标 URL: {config.forward_url or '未配置'}")
    logger.info(f"  转发规则数量: {len(config.forward_rules)}")
    
    yield
    
    logger.info("Forward Service 关闭")


# 创建 FastAPI 应用
app = FastAPI(
    title="Forward Service",
    description="消息转发服务 - 接收企微回调，转发到 Agent",
    version="1.1.0",
    lifespan=lifespan
)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 静态文件目录
STATIC_DIR = Path(__file__).parent / "static"


@app.get("/")
async def root():
    """根路径"""
    return {
        "service": "Forward Service",
        "version": "1.1.0",
        "status": "running"
    }


@app.get("/admin")
async def admin_page():
    """管理台页面"""
    admin_html = STATIC_DIR / "admin.html"
    if admin_html.exists():
        return FileResponse(admin_html)
    return {"error": "Admin page not found"}


@app.get("/health")
async def health():
    """健康检查"""
    errors = config.validate()
    return {
        "status": "healthy" if not errors else "unhealthy",
        "config_errors": errors,
        "forward_url": config.forward_url or None,
        "rules_count": len(config.forward_rules)
    }


# ============== 管理台 API ==============

@app.get("/admin/status")
async def admin_status():
    """获取服务状态（管理台用）"""
    return {
        "service": "Forward Service",
        "version": "1.1.0",
        "config": {
            "bot_key": config.bot_key[:10] + "..." if config.bot_key else None,
            "forward_url": config.forward_url,
            "rules_count": len(config.forward_rules),
            "timeout": config.timeout,
            "port": config.port
        },
        "stats": {
            "total_requests": len(request_logs),
            "recent_success": sum(1 for log in request_logs if log.status == "success"),
            "recent_error": sum(1 for log in request_logs if log.status == "error")
        }
    }


@app.get("/admin/rules")
async def admin_rules():
    """获取所有转发规则（管理台用）"""
    return {
        "default_url": config.forward_url,
        "rules": config.get_all_rules()
    }


@app.get("/admin/logs")
async def admin_logs(limit: int = 20):
    """获取最近的请求日志（管理台用）"""
    logs = list(request_logs)[:limit]
    return {
        "total": len(request_logs),
        "logs": [asdict(log) for log in logs]
    }


# ============== 规则管理 API ==============

class RuleInput(BaseModel):
    """规则输入模型"""
    chat_id: str
    url_template: str
    agent_id: str = ""
    api_key: str = ""
    name: str = ""
    timeout: int = 60


@app.post("/admin/rules")
async def add_rule(rule: RuleInput):
    """添加转发规则"""
    rule_data = {
        "url_template": rule.url_template,
        "agent_id": rule.agent_id,
        "api_key": rule.api_key,
        "name": rule.name,
        "timeout": rule.timeout
    }
    return config.add_rule(rule.chat_id, rule_data)


@app.put("/admin/rules/{chat_id}")
async def update_rule(chat_id: str, rule: RuleInput):
    """更新转发规则"""
    rule_data = {
        "url_template": rule.url_template,
        "agent_id": rule.agent_id,
        "api_key": rule.api_key,
        "name": rule.name,
        "timeout": rule.timeout
    }
    return config.update_rule(chat_id, rule_data)


@app.delete("/admin/rules/{chat_id}")
async def delete_rule(chat_id: str):
    """删除转发规则"""
    return config.delete_rule(chat_id)


# ============== 回调处理 ==============

@app.post("/callback")
async def handle_callback(
    request: Request,
    x_api_key: str | None = Header(None, alias="x-api-key")
):
    """
    处理企微机器人回调
    
    1. 接收用户消息
    2. 转发到 Agent
    3. 将结果发送给用户
    """
    # 验证鉴权（可选）
    if config.callback_auth_key and config.callback_auth_value:
        if x_api_key != config.callback_auth_value:
            logger.warning(f"回调鉴权失败: x_api_key={x_api_key}")
            return {"errcode": 401, "errmsg": "Unauthorized"}
    
    start_time = datetime.now()
    log_entry = None
    
    try:
        data = await request.json()
        
        chat_id = data.get("chatid", "")
        chat_type = data.get("chattype", "group")
        msg_type = data.get("msgtype", "")
        from_user = data.get("from", {})
        from_user_name = from_user.get("name", "unknown")
        
        logger.info(f"收到企微回调: chat_id={chat_id}, msg_type={msg_type}, from={from_user_name}")
        
        # 忽略某些事件类型
        if msg_type in ("event", "enter_chat"):
            logger.info(f"忽略事件类型: {msg_type}")
            return {"errcode": 0, "errmsg": "ok"}
        
        # 获取目标 URL（用于日志）
        target_url = config.get_target_url(chat_id)
        if not target_url:
            logger.warning(f"未找到 chat_id={chat_id} 的转发规则")
            return {"errcode": 0, "errmsg": "no forward rule"}
        
        # 提取消息内容
        content, image_url = extract_content(data)
        
        if not content and not image_url:
            logger.warning("消息内容为空，跳过处理")
            return {"errcode": 0, "errmsg": "empty content"}
        
        # 初始化日志条目
        log_entry = RequestLog(
            timestamp=datetime.now().isoformat(),
            chat_id=chat_id,
            from_user=from_user_name,
            content=content or "(image)",
            target_url=target_url,
            status="pending"
        )
        
        # 转发到 Agent
        result = await forward_to_agent(
            chat_id=chat_id,
            content=content or "",
            timeout=config.timeout
        )
        
        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
        
        if not result:
            log_entry.status = "error"
            log_entry.error = "转发失败或无配置"
            log_entry.duration_ms = duration_ms
            add_request_log(log_entry)
            
            # 发送错误提示给用户
            await send_reply(
                chat_id=chat_id,
                message="⚠️ 处理请求时发生错误，请稍后重试",
                msg_type="text"
            )
            return {"errcode": 0, "errmsg": "forward failed"}
        
        # 发送结果给用户
        send_result = await send_reply(
            chat_id=chat_id,
            message=result.reply,
            msg_type=result.msg_type
        )
        
        # 更新日志
        log_entry.status = "success" if send_result.get("success") else "error"
        log_entry.response = result.reply[:200] if result.reply else None
        log_entry.duration_ms = duration_ms
        if not send_result.get("success"):
            log_entry.error = send_result.get("error")
        add_request_log(log_entry)
        
        if send_result.get("success"):
            logger.info(f"回复已发送: chat_id={chat_id}")
        else:
            logger.error(f"发送回复失败: {send_result.get('error')}")
        
        return {"errcode": 0, "errmsg": "ok"}
        
    except Exception as e:
        logger.error(f"处理回调失败: {e}", exc_info=True)
        
        if log_entry:
            log_entry.status = "error"
            log_entry.error = str(e)
            log_entry.duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            add_request_log(log_entry)
        
        return {"errcode": -1, "errmsg": str(e)}


def main():
    """主函数"""
    import uvicorn
    uvicorn.run(
        "forward_service.app:app",
        host="0.0.0.0",
        port=config.port,
        reload=False
    )


if __name__ == "__main__":
    main()
