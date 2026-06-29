"""
Forward Service 客户端

提供与 Forward Service 通信的函数，支持 Direct（HTTP）和 Relay（WebSocket）两种模式
"""
import logging
from typing import Optional

import httpx
from pydantic import BaseModel

from ..config import config
from ..ws_manager import ws_manager

logger = logging.getLogger(__name__)


# ============== 数据模型 ==============

class ForwardRule(BaseModel):
    """转发规则配置（简化版）"""
    chat_id: str
    target_url: str  # 完整的目标 URL
    api_key: str = ""
    timeout: int = 60


# ============== 公共接口 ==============

async def get_forward_service_status() -> dict | None:
    """
    获取 Forward Service 状态
    
    - Direct 模式：直接 HTTP 请求
    - Relay 模式：通过 Worker 代理
    """
    if not config.forward_service_url:
        return {"error": "FORWARD_SERVICE_URL not configured"}
    
    if config.is_direct_mode:
        return await _http_get_forward_status()
    else:
        return await _ws_get_forward_status()


async def get_forward_service_logs(limit: int = 20) -> dict | None:
    """获取 Forward Service 日志"""
    if not config.forward_service_url:
        return {"error": "FORWARD_SERVICE_URL not configured"}
    
    if config.is_direct_mode:
        return await _http_get_forward_logs(limit)
    else:
        return await _ws_get_forward_logs(limit)


async def get_forward_service_rules() -> dict | None:
    """获取 Forward Service 转发规则"""
    if not config.forward_service_url:
        return {"error": "FORWARD_SERVICE_URL not configured"}
    
    if config.is_direct_mode:
        return await _http_get_forward_rules()
    else:
        return await _ws_get_forward_rules()


async def add_forward_rule(rule: ForwardRule) -> dict:
    """添加转发规则"""
    if not config.forward_service_url:
        return {"error": "FORWARD_SERVICE_URL not configured"}
    
    if config.is_direct_mode:
        return await _http_add_forward_rule(rule)
    else:
        return await _ws_add_forward_rule(rule)


async def update_forward_rule(chat_id: str, rule: ForwardRule) -> dict:
    """更新转发规则"""
    if not config.forward_service_url:
        return {"error": "FORWARD_SERVICE_URL not configured"}
    
    if config.is_direct_mode:
        return await _http_update_forward_rule(chat_id, rule)
    else:
        return await _ws_update_forward_rule(chat_id, rule)


async def delete_forward_rule(chat_id: str) -> dict:
    """删除转发规则"""
    if not config.forward_service_url:
        return {"error": "FORWARD_SERVICE_URL not configured"}
    
    if config.is_direct_mode:
        return await _http_delete_forward_rule(chat_id)
    else:
        return await _ws_delete_forward_rule(chat_id)


async def get_forward_service_config() -> dict:
    """获取 Forward Service 配置"""
    if not config.forward_service_url:
        return {"error": "FORWARD_SERVICE_URL not configured"}
    
    if config.is_direct_mode:
        return await _http_get_forward_config()
    else:
        return await _ws_get_forward_config()


async def update_forward_service_config(config_data: dict) -> dict:
    """更新 Forward Service 配置"""
    if not config.forward_service_url:
        return {"error": "FORWARD_SERVICE_URL not configured"}
    
    if config.is_direct_mode:
        return await _http_update_forward_config(config_data)
    else:
        return await _ws_update_forward_config(config_data)


async def reload_forward_service_config() -> dict:
    """重新加载 Forward Service 配置"""
    if not config.forward_service_url:
        return {"error": "FORWARD_SERVICE_URL not configured"}
    
    if config.is_direct_mode:
        return await _http_reload_forward_config()
    else:
        return await _ws_reload_forward_config()


# ============== HTTP 直接请求（Direct 模式）==============

async def _http_get_forward_status() -> dict:
    """通过 HTTP 获取 Forward Service 状态"""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{config.forward_service_url}/admin/status")
            if response.status_code == 200:
                data = response.json()
                data["_source"] = "direct_http"
                return data
            return {"error": f"HTTP {response.status_code}"}
    except Exception as e:
        logger.warning(f"获取 Forward Service 状态失败: {e}")
        return {"error": str(e)}


async def _http_get_forward_logs(limit: int) -> dict:
    """通过 HTTP 获取 Forward Service 日志"""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{config.forward_service_url}/admin/logs?limit={limit}")
            if response.status_code == 200:
                data = response.json()
                return {"success": True, "logs": data.get("logs", [])}
            return {"success": False, "error": f"HTTP {response.status_code}", "logs": []}
    except Exception as e:
        logger.warning(f"获取 Forward Service 日志失败: {e}")
        return {"success": False, "error": str(e), "logs": []}


async def _http_get_forward_rules() -> dict:
    """通过 HTTP 获取 Forward Service 规则"""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{config.forward_service_url}/admin/rules")
            if response.status_code == 200:
                return response.json()
            return {"error": f"HTTP {response.status_code}"}
    except Exception as e:
        logger.warning(f"获取 Forward Service 规则失败: {e}")
        return {"error": str(e)}


async def _http_add_forward_rule(rule: ForwardRule) -> dict:
    """通过 HTTP 添加转发规则"""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.post(
                f"{config.forward_service_url}/admin/rules",
                json=rule.model_dump()
            )
            return response.json()
    except Exception as e:
        return {"error": str(e)}


async def _http_update_forward_rule(chat_id: str, rule: ForwardRule) -> dict:
    """通过 HTTP 更新转发规则"""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.put(
                f"{config.forward_service_url}/admin/rules/{chat_id}",
                json=rule.model_dump()
            )
            return response.json()
    except Exception as e:
        return {"error": str(e)}


async def _http_delete_forward_rule(chat_id: str) -> dict:
    """通过 HTTP 删除转发规则"""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.delete(
                f"{config.forward_service_url}/admin/rules/{chat_id}"
            )
            return response.json()
    except Exception as e:
        return {"error": str(e)}


async def _http_get_forward_config() -> dict:
    """通过 HTTP 获取配置"""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{config.forward_service_url}/admin/config")
            if response.status_code == 200:
                return response.json()
            return {"error": f"HTTP {response.status_code}"}
    except Exception as e:
        logger.warning(f"获取 Forward Service 配置失败: {e}")
        return {"error": str(e)}


async def _http_update_forward_config(config_data: dict) -> dict:
    """通过 HTTP 更新配置"""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.put(
                f"{config.forward_service_url}/admin/config",
                json=config_data
            )
            if response.status_code == 200:
                return response.json()
            return {"error": f"HTTP {response.status_code}"}
    except Exception as e:
        logger.warning(f"更新 Forward Service 配置失败: {e}")
        return {"error": str(e)}


async def _http_reload_forward_config() -> dict:
    """通过 HTTP 重新加载配置"""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.post(f"{config.forward_service_url}/admin/config/reload")
            if response.status_code == 200:
                return response.json()
            return {"error": f"HTTP {response.status_code}"}
    except Exception as e:
        logger.warning(f"重新加载 Forward Service 配置失败: {e}")
        return {"error": str(e)}


# ============== WebSocket 代理请求（Relay 模式）==============

async def _ws_get_forward_status() -> dict:
    """通过 Worker 代理获取 Forward Service 状态"""
    if not ws_manager.has_worker:
        return {"error": "No worker connected"}
    
    try:
        result = await ws_manager.send_request(
            action="get_forward_status",
            payload={"url": config.forward_service_url},
            timeout=10
        )
        result["_source"] = "worker_proxy"
        return result
    except Exception as e:
        logger.warning(f"通过 Worker 获取 Forward Service 状态失败: {e}")
        return {"error": str(e)}


async def _ws_get_forward_logs(limit: int) -> dict:
    """通过 Worker 代理获取 Forward Service 日志"""
    if not ws_manager.has_worker:
        return {"success": False, "error": "No worker connected", "logs": []}
    
    try:
        data = await ws_manager.send_request(
            action="get_forward_logs",
            payload={"url": config.forward_service_url, "limit": limit},
            timeout=10
        )
        return {"success": True, "logs": data.get("logs", [])}
    except Exception as e:
        logger.warning(f"通过 Worker 获取 Forward Service 日志失败: {e}")
        return {"success": False, "error": str(e), "logs": []}


async def _ws_get_forward_rules() -> dict:
    """通过 Worker 代理获取 Forward Service 规则"""
    if not ws_manager.has_worker:
        return {"error": "No worker connected"}
    
    try:
        return await ws_manager.send_request(
            action="get_forward_rules",
            payload={"url": config.forward_service_url},
            timeout=10
        )
    except Exception as e:
        logger.warning(f"通过 Worker 获取 Forward Service 规则失败: {e}")
        return {"error": str(e)}


async def _ws_add_forward_rule(rule: ForwardRule) -> dict:
    """通过 Worker 代理添加转发规则"""
    if not ws_manager.has_worker:
        return {"error": "No worker connected"}
    
    try:
        return await ws_manager.send_request(
            action="add_forward_rule",
            payload={"url": config.forward_service_url, "rule": rule.model_dump()},
            timeout=10
        )
    except Exception as e:
        return {"error": str(e)}


async def _ws_update_forward_rule(chat_id: str, rule: ForwardRule) -> dict:
    """通过 Worker 代理更新转发规则"""
    if not ws_manager.has_worker:
        return {"error": "No worker connected"}
    
    try:
        return await ws_manager.send_request(
            action="update_forward_rule",
            payload={"url": config.forward_service_url, "chat_id": chat_id, "rule": rule.model_dump()},
            timeout=10
        )
    except Exception as e:
        return {"error": str(e)}


async def _ws_delete_forward_rule(chat_id: str) -> dict:
    """通过 Worker 代理删除转发规则"""
    if not ws_manager.has_worker:
        return {"error": "No worker connected"}
    
    try:
        return await ws_manager.send_request(
            action="delete_forward_rule",
            payload={"url": config.forward_service_url, "chat_id": chat_id},
            timeout=10
        )
    except Exception as e:
        return {"error": str(e)}


async def _ws_get_forward_config() -> dict:
    """通过 Worker 代理获取配置"""
    if not ws_manager.has_worker:
        return {"error": "No worker connected"}
    
    try:
        return await ws_manager.send_request(
            action="get_forward_config",
            payload={"url": config.forward_service_url},
            timeout=10
        )
    except Exception as e:
        logger.warning(f"通过 Worker 获取 Forward Service 配置失败: {e}")
        return {"error": str(e)}


async def _ws_update_forward_config(config_data: dict) -> dict:
    """通过 Worker 代理更新配置"""
    if not ws_manager.has_worker:
        return {"error": "No worker connected"}
    
    try:
        return await ws_manager.send_request(
            action="update_forward_config",
            payload={"url": config.forward_service_url, "config": config_data},
            timeout=10
        )
    except Exception as e:
        logger.warning(f"通过 Worker 更新 Forward Service 配置失败: {e}")
        return {"error": str(e)}


async def _ws_reload_forward_config() -> dict:
    """通过 Worker 代理重新加载配置"""
    if not ws_manager.has_worker:
        return {"error": "No worker connected"}
    
    try:
        return await ws_manager.send_request(
            action="reload_forward_config",
            payload={"url": config.forward_service_url},
            timeout=10
        )
    except Exception as e:
        logger.warning(f"通过 Worker 重新加载 Forward Service 配置失败: {e}")
        return {"error": str(e)}
