"""
管理台 API 处理器

提供统一的管理台 API，整合 HIL Server、Worker、Forward Service 的状态
"""
import logging
import hashlib
import secrets
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

import httpx
import jwt
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel

from ..config import config
from ..ws_manager import ws_manager
from ..storage import storage
from ..idle_hint_config import idle_hint_config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin"])

# 静态文件目录
STATIC_DIR = Path(__file__).parent.parent / "static"

# JWT 配置
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24

# 安全认证
security = HTTPBearer(auto_error=False)


# ============== 数据模型 ==============

class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    expires_at: str


class ForwardRule(BaseModel):
    chat_id: str
    url_template: str
    agent_id: str
    api_key: str
    timeout: int = 60


# ============== 认证工具函数 ==============

def create_token(username: str) -> tuple[str, datetime]:
    """创建 JWT Token"""
    expires_at = datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS)
    payload = {
        "sub": username,
        "exp": expires_at,
        "iat": datetime.utcnow()
    }
    token = jwt.encode(payload, config.admin_token_secret, algorithm=JWT_ALGORITHM)
    return token, expires_at


def verify_token(token: str) -> Optional[str]:
    """验证 JWT Token，返回用户名"""
    try:
        payload = jwt.decode(token, config.admin_token_secret, algorithms=[JWT_ALGORITHM])
        return payload.get("sub")
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> str:
    """获取当前登录用户"""
    if not credentials:
        raise HTTPException(status_code=401, detail="未登录")
    
    username = verify_token(credentials.credentials)
    if not username:
        raise HTTPException(status_code=401, detail="Token 无效或已过期")
    
    return username


def require_auth(request: Request) -> bool:
    """检查是否需要认证（用于页面）"""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return False
    token = auth_header[7:]
    return verify_token(token) is not None


# ============== 认证 API ==============

@router.post("/api/login")
async def login(request: LoginRequest) -> LoginResponse:
    """登录获取 Token"""
    if request.username != config.admin_username or request.password != config.admin_password:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    
    token, expires_at = create_token(request.username)
    logger.info(f"用户登录成功: {request.username}")
    
    return LoginResponse(
        token=token,
        expires_at=expires_at.isoformat()
    )


@router.get("/api/verify")
async def verify_auth(user: str = Depends(get_current_user)):
    """验证 Token 有效性"""
    return {"valid": True, "username": user}


# ============== 页面路由 ==============

@router.get("")
async def admin_page():
    """管理台页面 - 重定向到新版管理台"""
    return RedirectResponse(url="/console", status_code=302)


# ============== API 路由 ==============

@router.get("/api/overview")
async def get_overview(user: str = Depends(get_current_user)):
    """
    获取所有服务的概览状态（需要登录）
    """
    mode = config.effective_mode
    
    # HIL Server 状态
    hil_status = {
        "service": "HIL Server",
        "version": "2.0.0",
        "status": "running",
        "mode": mode,
        "port": config.port,
        "sessions": {
            "active": len([s for s in storage._sessions.values() if s.status == "waiting"]),
            "total": len(storage._sessions)
        }
    }
    
    # Worker 状态（仅 Relay 模式）
    worker_status = None
    if mode == "relay":
        # 使用 get_all_workers 获取完整的 Worker 信息
        workers = ws_manager.get_all_workers()
        
        worker_status = {
            "connected": ws_manager.has_worker,
            "count": len(workers),
            "workers": workers
        }
    
    # Forward Service 状态
    forward_status = await _get_forward_service_status()
    
    return {
        "timestamp": datetime.now().isoformat(),
        "mode": mode,
        "hil_server": hil_status,
        "worker": worker_status,
        "forward_service": forward_status
    }


@router.get("/api/hil/sessions")
async def get_hil_sessions(user: str = Depends(get_current_user)):
    """获取 HIL Server 会话列表（需要登录）"""
    sessions = []
    for session in storage._sessions.values():
        sessions.append({
            "session_id": session.session_id,
            "short_id": session.short_id,
            "chat_id": session.chat_id,
            "chat_type": session.chat_type,
            "message": session.message[:100] + "..." if len(session.message) > 100 else session.message,
            "project_name": session.project_name,
            "status": session.status,
            "replies_count": len(session.replies),
            "created_at": session.created_at.isoformat(),
            "expire_at": session.expire_at.isoformat()
        })
    
    # 按创建时间倒序
    sessions.sort(key=lambda x: x["created_at"], reverse=True)
    
    return {
        "total": len(sessions),
        "sessions": sessions[:50]  # 最多返回 50 条
    }


@router.get("/api/forward/status")
async def get_forward_status(user: str = Depends(get_current_user)):
    """获取 Forward Service 状态（需要登录）"""
    return await _get_forward_service_status()


@router.get("/api/forward/logs")
async def get_forward_logs(limit: int = 20, user: str = Depends(get_current_user)):
    """获取 Forward Service 日志（需要登录）"""
    return await _get_forward_service_logs(limit)


@router.get("/api/forward/rules")
async def get_forward_rules(user: str = Depends(get_current_user)):
    """获取 Forward Service 转发规则（需要登录）"""
    return await _get_forward_service_rules()



@router.get("/api/forward/config")
async def get_forward_config(user: str = Depends(get_current_user)):
    """获取 Forward Service 完整配置（需要登录）"""
    return await _get_forward_service_config()


@router.put("/api/forward/config")
async def update_forward_config(request: Request, user: str = Depends(get_current_user)):
    """更新 Forward Service 完整配置（需要登录）"""
    data = await request.json()
    return await _update_forward_service_config(data)


@router.post("/api/forward/config/reload")
async def reload_forward_config(user: str = Depends(get_current_user)):
    """重新加载 Forward Service 配置（需要登录）"""
    return await _reload_forward_service_config()


# ============== Forward Service 代理 API ==============

@router.api_route(
    "/api/forward/proxy/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE"],
)
async def forward_proxy(
    request: Request,
    path: str,
    user: str = Depends(get_current_user)
):
    """
    代理请求到 Forward Service
    
    将 /admin/api/forward/proxy/* 的请求转发到 FORWARD_SERVICE_URL/*
    """
    if not config.forward_service_url:
        raise HTTPException(status_code=503, detail="FORWARD_SERVICE_URL not configured")
    
    # 构建目标 URL
    target_url = f"{config.forward_service_url}/{path}"
    
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # 获取请求体（如果有）
            body = None
            if request.method in ["POST", "PUT"]:
                body = await request.body()
            
            # 构建请求头
            headers = {}
            if "content-type" in request.headers:
                headers["content-type"] = request.headers["content-type"]
            
            # 发送请求
            response = await client.request(
                method=request.method,
                url=target_url,
                content=body,
                headers=headers,
                params=request.query_params,
            )
            
            return response.json()
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Forward Service 请求超时")
    except Exception as e:
        logger.error(f"代理请求失败: {e}")
        raise HTTPException(status_code=502, detail=f"Forward Service 请求失败: {str(e)}")


# ============== 转发规则管理 API ==============

@router.post("/api/forward/rules")
async def add_forward_rule(rule: ForwardRule, user: str = Depends(get_current_user)):
    """添加转发规则（需要登录）"""
    return await _add_forward_rule(rule)


@router.put("/api/forward/rules/{chat_id}")
async def update_forward_rule(chat_id: str, rule: ForwardRule, user: str = Depends(get_current_user)):
    """更新转发规则（需要登录）"""
    return await _update_forward_rule(chat_id, rule)


@router.delete("/api/forward/rules/{chat_id}")
async def delete_forward_rule(chat_id: str, user: str = Depends(get_current_user)):
    """删除转发规则（需要登录）"""
    return await _delete_forward_rule(chat_id)


# ============== Worker 管理 API ==============

@router.get("/api/workers")
async def get_workers(user: str = Depends(get_current_user)):
    """
    获取所有 Worker 列表（需要登录）
    
    返回每个 Worker 的详细信息：
    - worker_id: Worker 标识
    - ip_address: IP 地址
    - hostname: 主机名
    - callback_port: 回调端口
    - bot_key: 机器人 Key（部分显示）
    - forward_service_url: 关联的 Forward Service 地址
    - connected_at: 连接时间
    - last_heartbeat: 最后心跳时间
    - is_alive: 是否存活
    """
    workers = ws_manager.get_all_workers()
    return {
        "count": len(workers),
        "workers": workers
    }


@router.get("/api/workers/{worker_id}/config")
async def get_worker_config(worker_id: str, user: str = Depends(get_current_user)):
    """
    获取指定 Worker 的配置（需要登录）
    
    通过 WebSocket 向 Worker 请求其配置
    """
    # 检查 Worker 是否存在
    if worker_id not in ws_manager._workers:
        raise HTTPException(status_code=404, detail=f"Worker not found: {worker_id}")
    
    worker = ws_manager._workers[worker_id]
    
    # 返回 Worker 的基本配置（从注册信息中获取）
    return {
        "worker_id": worker.worker_id,
        "ip_address": worker.ip_address,
        "hostname": worker.hostname,
        "callback_port": worker.callback_port,
        "bot_key": worker.bot_key,
        "hil_url": worker.hil_url,
        "config_file": worker.config_file,
        "forward_service_url": worker.forward_service_url
    }


class WorkerConfigUpdate(BaseModel):
    bot_key: str | None = None
    hil_url: str | None = None
    callback_port: int | None = None


class IdleHintConfigRequest(BaseModel):
    """空闲提示消息配置请求"""
    template: str
    enabled: bool = True
    chat_id: str | None = None  # 如果为 None，则更新全局默认配置


@router.put("/api/workers/{worker_id}/config")
async def update_worker_config(
    worker_id: str, 
    config_update: WorkerConfigUpdate,
    user: str = Depends(get_current_user)
):
    """
    更新指定 Worker 的配置（需要登录）
    
    通过 WebSocket 向 Worker 发送配置更新请求
    """
    if not ws_manager.has_worker:
        raise HTTPException(status_code=503, detail="No worker connected")
    
    try:
        # 构造更新 payload
        payload = {}
        if config_update.bot_key is not None:
            payload["bot_key"] = config_update.bot_key
        if config_update.hil_url is not None:
            payload["hil_url"] = config_update.hil_url
        if config_update.callback_port is not None:
            payload["callback_port"] = config_update.callback_port
        
        result = await ws_manager.send_request(
            action="update_worker_config",
            payload=payload,
            timeout=10
        )
        
        return result
    except Exception as e:
        logger.error(f"更新 Worker 配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============== 内部函数 ==============

async def _get_forward_service_status() -> dict | None:
    """
    获取 Forward Service 状态
    
    - Direct 模式：直接 HTTP 请求
    - Relay 模式：通过 Worker 代理
    """
    if not config.forward_service_url:
        return {"error": "FORWARD_SERVICE_URL not configured"}
    
    if config.is_direct_mode:
        # Direct 模式：直接请求
        return await _http_get_forward_status()
    else:
        # Relay 模式：通过 Worker 代理
        return await _ws_get_forward_status()


async def _get_forward_service_logs(limit: int = 20) -> dict | None:
    """获取 Forward Service 日志"""
    if not config.forward_service_url:
        return {"error": "FORWARD_SERVICE_URL not configured"}
    
    if config.is_direct_mode:
        return await _http_get_forward_logs(limit)
    else:
        return await _ws_get_forward_logs(limit)


async def _get_forward_service_rules() -> dict | None:
    """获取 Forward Service 转发规则"""
    if not config.forward_service_url:
        return {"error": "FORWARD_SERVICE_URL not configured"}
    
    if config.is_direct_mode:
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


async def _add_forward_rule(rule: ForwardRule) -> dict:
    """添加转发规则"""
    if not config.forward_service_url:
        return {"error": "FORWARD_SERVICE_URL not configured"}
    
    if config.is_direct_mode:
        return await _http_add_forward_rule(rule)
    else:
        return await _ws_add_forward_rule(rule)


async def _update_forward_rule(chat_id: str, rule: ForwardRule) -> dict:
    """更新转发规则"""
    if not config.forward_service_url:
        return {"error": "FORWARD_SERVICE_URL not configured"}
    
    if config.is_direct_mode:
        return await _http_update_forward_rule(chat_id, rule)
    else:
        return await _ws_update_forward_rule(chat_id, rule)


async def _delete_forward_rule(chat_id: str) -> dict:
    """删除转发规则"""
    if not config.forward_service_url:
        return {"error": "FORWARD_SERVICE_URL not configured"}
    
    if config.is_direct_mode:
        return await _http_delete_forward_rule(chat_id)
    else:
        return await _ws_delete_forward_rule(chat_id)


# HTTP 规则管理
async def _http_add_forward_rule(rule: ForwardRule) -> dict:
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
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.delete(
                f"{config.forward_service_url}/admin/rules/{chat_id}"
            )
            return response.json()
    except Exception as e:
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
        # 添加 success 字段以适配前端
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


# WebSocket 规则管理
async def _ws_add_forward_rule(rule: ForwardRule) -> dict:
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


# ============== 空闲提示消息配置 API ==============

@router.get("/api/idle-hint-config")
async def get_idle_hint_config(user: str = Depends(get_current_user)):
    """
    获取空闲提示消息配置（需要登录）
    
    返回：
    - default: 全局默认配置
    - chat_configs: 按 chat_id 的自定义配置
    """
    try:
        configs = idle_hint_config.get_all_configs()
        return {
            "success": True,
            "data": configs
        }
    except Exception as e:
        logger.error(f"获取空闲提示消息配置失败: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e)
        }


@router.post("/api/idle-hint-config")
async def update_idle_hint_config(
    config_request: IdleHintConfigRequest,
    user: str = Depends(get_current_user)
):
    """
    更新空闲提示消息配置（需要登录）
    
    如果 chat_id 为 None，则更新全局默认配置
    否则更新指定 chat_id 的配置
    """
    try:
        if config_request.chat_id:
            # 更新指定 chat_id 的配置
            result = idle_hint_config.update_chat_config(
                chat_id=config_request.chat_id,
                template=config_request.template,
                enabled=config_request.enabled,
                updated_by=user
            )
        else:
            # 更新全局默认配置
            result = idle_hint_config.update_default_config(
                template=config_request.template,
                enabled=config_request.enabled,
                updated_by=user
            )
        
        return result
    except Exception as e:
        logger.error(f"更新空闲提示消息配置失败: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e)
        }


@router.delete("/api/idle-hint-config/{chat_id}")
async def delete_idle_hint_config(
    chat_id: str,
    user: str = Depends(get_current_user)
):
    """
    删除指定 chat_id 的自定义配置（需要登录）
    
    删除后将使用全局默认配置
    """
    try:
        result = idle_hint_config.delete_chat_config(chat_id)
        return result
    except Exception as e:
        logger.error(f"删除空闲提示消息配置失败: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e)
        }


# ============== Forward Config 管理（新增 - 多 Bot 支持） ==============

async def _get_forward_service_config() -> dict:
    """获取 Forward Service 完整配置"""
    if not config.forward_service_url:
        return {"error": "FORWARD_SERVICE_URL not configured"}
    
    if config.is_direct_mode:
        return await _http_get_forward_config()
    else:
        return await _ws_get_forward_config()


async def _update_forward_service_config(config_data: dict) -> dict:
    """更新 Forward Service 配置"""
    if not config.forward_service_url:
        return {"error": "FORWARD_SERVICE_URL not configured"}
    
    if config.is_direct_mode:
        return await _http_update_forward_config(config_data)
    else:
        return await _ws_update_forward_config(config_data)


async def _reload_forward_service_config() -> dict:
    """重新加载 Forward Service 配置"""
    if not config.forward_service_url:
        return {"error": "FORWARD_SERVICE_URL not configured"}
    
    if config.is_direct_mode:
        return await _http_reload_forward_config()
    else:
        return await _ws_reload_forward_config()


async def _http_get_forward_config() -> dict:
    """通过 HTTP 获取 Forward Service 完整配置"""
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
    """通过 HTTP 更新 Forward Service 配置"""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
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
    """通过 HTTP 重新加载 Forward Service 配置"""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.post(f"{config.forward_service_url}/admin/config/reload")
            if response.status_code == 200:
                return response.json()
            return {"error": f"HTTP {response.status_code}"}
    except Exception as e:
        logger.warning(f"重新加载 Forward Service 配置失败: {e}")
        return {"error": str(e)}


async def _ws_get_forward_config() -> dict:
    """通过 Worker 代理获取 Forward Service 配置"""
    try:
        response = await ws_manager.send_request(
            action="http_get",
            payload={"url": f"{config.forward_service_url}/admin/config"},
            timeout=5
        )
        return response
    except Exception as e:
        logger.warning(f"通过 Worker 获取 Forward Service 配置失败: {e}")
        return {"error": str(e)}


async def _ws_update_forward_config(config_data: dict) -> dict:
    """通过 Worker 代理更新 Forward Service 配置"""
    try:
        response = await ws_manager.send_request(
            action="http_put",
            payload={
                "url": f"{config.forward_service_url}/admin/config",
                "data": config_data
            },
            timeout=10
        )
        return response
    except Exception as e:
        logger.warning(f"通过 Worker 更新 Forward Service 配置失败: {e}")
        return {"error": str(e)}


async def _ws_reload_forward_config() -> dict:
    """通过 Worker 代理重新加载 Forward Service 配置"""
    try:
        response = await ws_manager.send_request(
            action="http_post",
            payload={"url": f"{config.forward_service_url}/admin/config/reload"},
            timeout=5
        )
        return response
    except Exception as e:
        logger.warning(f"通过 Worker 重新加载 Forward Service 配置失败: {e}")
        return {"error": str(e)}
