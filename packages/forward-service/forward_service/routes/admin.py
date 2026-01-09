"""
管理 API 路由

/admin/* 相关接口
"""
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from pathlib import Path

from ..config import config
from ..database import get_db_manager
from ..repository import get_forward_log_repository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# ============== 请求日志（持久化到数据库） ==============

@dataclass
class RequestLogData:
    """请求日志数据（用于创建日志）"""
    chat_id: str
    from_user_id: str
    from_user_name: str
    content: str
    target_url: str
    msg_type: str = "text"
    bot_key: Optional[str] = None
    bot_name: Optional[str] = None
    session_id: Optional[str] = None
    status: str = "pending"
    response: Optional[str] = None
    error: Optional[str] = None
    duration_ms: int = 0


async def add_request_log(log_data: RequestLogData) -> int | None:
    """
    添加请求日志到数据库
    
    Returns:
        日志 ID，用于后续更新响应信息
    """
    try:
        db_manager = get_db_manager()
        async with db_manager.get_session() as session:
            repo = get_forward_log_repository(session)
            log = await repo.create(
                chat_id=log_data.chat_id,
                from_user_id=log_data.from_user_id,
                from_user_name=log_data.from_user_name,
                content=log_data.content,
                target_url=log_data.target_url,
                msg_type=log_data.msg_type,
                bot_key=log_data.bot_key,
                bot_name=log_data.bot_name,
                session_id=log_data.session_id,
                status=log_data.status,
                response=log_data.response,
                error=log_data.error,
                duration_ms=log_data.duration_ms,
            )
            return log.id
    except Exception as e:
        logger.error(f"添加请求日志失败: {e}")
        return None


async def update_request_log(
    log_id: int,
    status: str,
    response: str = None,
    error: str = None,
    session_id: str = None,
    duration_ms: int = None,
):
    """更新请求日志的响应信息"""
    try:
        db_manager = get_db_manager()
        async with db_manager.get_session() as session:
            repo = get_forward_log_repository(session)
            await repo.update_response(
                log_id=log_id,
                status=status,
                response=response,
                error=error,
                session_id=session_id,
                duration_ms=duration_ms,
            )
    except Exception as e:
        logger.error(f"更新请求日志失败: {e}")


# ============== 静态文件 ==============

STATIC_DIR = Path(__file__).parent.parent / "static"


@router.get("")
async def admin_page():
    """管理台页面"""
    admin_html = STATIC_DIR / "admin.html"
    if admin_html.exists():
        return FileResponse(admin_html)
    return {"error": "Admin page not found"}


# ============== 状态和配置 API ==============

@router.get("/status")
async def admin_status():
    """获取服务状态（管理台用）"""
    return {
        "service": "Forward Service",
        "version": "3.0.0",
        "config": {
            "default_bot_key": config.default_bot_key[:10] + "..." if config.default_bot_key else None,
            "bots_count": len(config.bots),
            "timeout": config.timeout,
            "port": config.port
        },
        "stats": {
            "total_requests": len(request_logs),
            "recent_success": sum(1 for log in request_logs if log.status == "success"),
            "recent_error": sum(1 for log in request_logs if log.status == "error")
        }
    }


@router.get("/config")
async def get_config():
    """获取完整配置（管理台用）"""
    return config.get_config_dict()


@router.put("/config")
async def update_config(request: Request):
    """更新完整配置（管理台用）"""
    try:
        data = await request.json()
        result = await config.update_from_dict(data)
        return result
    except Exception as e:
        logger.error(f"更新配置失败: {e}")
        return {"success": False, "error": str(e)}


@router.post("/config/reload")
async def reload_config():
    """重新加载配置"""
    return await config.reload_config()


# ============== 兼容性 API（旧版规则管理） ==============

@router.get("/rules")
async def admin_rules():
    """
    获取所有 Bot 配置（兼容旧 API）
    
    为了与旧版管理台兼容，将 bots 格式转换为类似 rules 的格式
    以 bot_key 作为 key，bot 配置作为 value
    """
    bots_dict = {}
    
    for bot_key, bot in config.bots.items():
        bots_dict[bot_key] = {
            "url_template": bot.forward_config.url_template,
            "agent_id": bot.forward_config.agent_id,
            "api_key": bot.forward_config.api_key,
            "name": bot.name,
            "timeout": bot.forward_config.timeout,
            "bot_name": bot.name,
            "description": bot.description,
            "access_mode": bot.access_control.mode,
            "enabled": bot.enabled,
            "is_default": bot_key == config.default_bot_key
        }
    
    return {
        "default_url": config.default_bot_key,
        "default_bot_key": config.default_bot_key,
        "rules": bots_dict,
        "bots": bots_dict
    }


@router.get("/logs")
async def admin_logs(limit: int = 100):
    """获取最近的请求日志（管理台用）"""
    try:
        db_manager = get_db_manager()
        async with db_manager.get_session() as session:
            repo = get_forward_log_repository(session)
            logs = await repo.get_recent(limit=limit)
            total = await repo.count()
            
            return {
                "total": total,
                "logs": [log.to_dict() for log in logs]
            }
    except Exception as e:
        logger.error(f"获取日志失败: {e}")
        return {
            "total": 0,
            "logs": [],
            "error": str(e)
        }


@router.get("/mode")
async def get_mode():
    """获取当前配置模式（管理台用）"""
    return {
        "mode": "database",
        "supports_bot_api": True,
        "version": "3.0.0"
    }
