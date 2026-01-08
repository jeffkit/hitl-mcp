"""
Forward Service 代理

代理请求到 Forward Service，支持 HTTP 直接请求（Direct 模式）和 WebSocket 代理（Relay 模式）
"""
import logging

import httpx
from fastapi import APIRouter, Request, Depends

from ..config import config
from ..ws_manager import ws_manager
from .auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Forward Proxy"])


# ============== Forward Service 代理 API ==============

@router.api_route(
    "/api/forward/proxy/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE"]
)
async def forward_proxy(
    path: str,
    request: Request,
    user: str = Depends(get_current_user)
):
    """
    代理请求到 Forward Service
    
    将 /admin/api/forward/proxy/xxx 代理到 forward-service 的 /xxx
    """
    forward_url = config.forward_service_url
    if not forward_url:
        return {"success": False, "error": "Forward Service URL 未配置"}
    
    # 构建目标 URL
    target_url = f"{forward_url}/{path}"
    
    # 获取请求体（如果有）
    body = None
    if request.method in ("POST", "PUT"):
        try:
            body = await request.json()
        except Exception:
            body = None
    
    # 代理请求
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            if request.method == "GET":
                response = await client.get(target_url)
            elif request.method == "POST":
                response = await client.post(target_url, json=body)
            elif request.method == "PUT":
                response = await client.put(target_url, json=body)
            elif request.method == "DELETE":
                response = await client.delete(target_url)
            else:
                return {"success": False, "error": f"不支持的方法: {request.method}"}
            
            if response.status_code == 200:
                return response.json()
            else:
                return {
                    "success": False,
                    "error": f"Forward Service 返回错误: {response.status_code}"
                }
    except Exception as e:
        logger.error(f"代理请求失败: {e}")
        return {"success": False, "error": str(e)}


# ============== 获取 Forward Service 状态 ==============

async def get_forward_status_internal() -> dict:
    """获取 Forward Service 状态（内部函数）"""
    mode = config.effective_mode
    
    if mode == "direct":
        return await _http_get_forward_status()
    else:
        return await _ws_get_forward_status()


async def get_forward_logs_internal(limit: int = 20) -> dict:
    """获取 Forward Service 日志（内部函数）"""
    mode = config.effective_mode
    
    if mode == "direct":
        return await _http_get_forward_logs(limit)
    else:
        return await _ws_get_forward_logs(limit)


async def get_forward_rules_internal() -> dict:
    """获取 Forward Service 规则（内部函数）"""
    mode = config.effective_mode
    
    if mode == "direct":
        return await _http_get_forward_rules()
    else:
        return await _ws_get_forward_rules()


# ============== HTTP 直接请求（Direct 模式）==============

async def _http_get_forward_status() -> dict:
    """通过 HTTP 获取 Forward Service 状态"""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{config.forward_service_url}/admin/status")
            if response.status_code == 200:
                return response.json()
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
                # 添加 success 字段以适配前端
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


# ============== WebSocket 代理请求（Relay 模式）==============

async def _ws_get_forward_status() -> dict:
    """通过 WebSocket 获取 Forward Service 状态"""
    if not ws_manager.has_worker:
        return {"error": "没有 Worker 连接"}
    
    try:
        result = await ws_manager.send_request("get_forward_status", {})
        return result.get("data", result)
    except Exception as e:
        logger.warning(f"获取 Forward Service 状态失败: {e}")
        return {"error": str(e)}


async def _ws_get_forward_logs(limit: int) -> dict:
    """通过 WebSocket 获取 Forward Service 日志"""
    if not ws_manager.has_worker:
        return {"success": False, "error": "没有 Worker 连接", "logs": []}
    
    try:
        result = await ws_manager.send_request("get_forward_logs", {"limit": limit})
        data = result.get("data", result)
        # 添加 success 字段以适配前端
        return {"success": True, "logs": data.get("logs", [])}
    except Exception as e:
        logger.warning(f"获取 Forward Service 日志失败: {e}")
        return {"success": False, "error": str(e), "logs": []}


async def _ws_get_forward_rules() -> dict:
    """通过 WebSocket 获取 Forward Service 规则"""
    if not ws_manager.has_worker:
        return {"error": "没有 Worker 连接"}
    
    try:
        result = await ws_manager.send_request("get_forward_rules", {})
        return result.get("data", result)
    except Exception as e:
        logger.warning(f"获取 Forward Service 规则失败: {e}")
        return {"error": str(e)}
