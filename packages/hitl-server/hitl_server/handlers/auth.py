"""
认证 API 处理器

处理管理台登录、Token 验证
"""
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

import jwt
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from ..config import config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Auth"])

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


# ============== 认证 API ==============

@router.post("/api/login")
async def login(request: LoginRequest) -> LoginResponse:
    """管理台登录"""
    if request.username != config.admin_username:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    
    if request.password != config.admin_password:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    
    token, expires_at = create_token(request.username)
    
    return LoginResponse(
        token=token,
        expires_at=expires_at.isoformat()
    )


@router.get("/api/verify")
async def verify_auth(user: str = Depends(get_current_user)):
    """验证登录状态"""
    return {"valid": True, "user": user}


# ============== MCP→Server API Token 鉴权 ==============
#
# 共享部署模式下，/api/* 接口需要 Bearer Token 鉴权，避免任意人能冒充任意
# chat_id 发消息。支持两种凭证：
#   1) HITL_API_KEY（单一 key，不限制 chat_id）—— 可信单租户场景
#   2) HITL_API_TOKENS（JSON: {token: [allowed_chat_ids]}）—— 多租户白名单
# tokens 优先于 api_key。本地非共享模式下若两者都未配置，则不鉴权（向后兼容）。


def _load_api_tokens() -> dict[str, list[str]]:
    """解析 HITL_API_TOKENS JSON 字符串为 {token: [chat_id, ...]}。"""
    raw = (config.api_tokens or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"HITL_API_TOKENS 解析失败：{e}；将以空映射处理（仅 api_key 生效）")
        return {}
    if not isinstance(data, dict):
        logger.error("HITL_API_TOKENS 顶层不是 JSON 对象；将以空映射处理")
        return {}
    cleaned: dict[str, list[str]] = {}
    for tok, ids in data.items():
        if not isinstance(tok, str) or not tok:
            continue
        if isinstance(ids, list):
            cleaned[tok] = [str(x) for x in ids]
        else:
            cleaned[tok] = []
    return cleaned


def _auth_enabled() -> bool:
    """是否启用 API 鉴权：shared_mode 强制启用；否则配了 key/tokens 也启用。"""
    return bool(config.shared_mode or config.api_key or _load_api_tokens())


def _resolve_token_scope(token: str) -> tuple[bool, list[str] | None]:
    """
    校验 token，返回 (是否通过, 允许的 chat_id 列表)。
    - None 表示不限制（可发任意 chat_id）
    - 列表表示白名单
    """
    tokens = _load_api_tokens()
    if tokens and token in tokens:
        allowed = tokens[token]
        return True, (allowed if allowed else None)
    if config.api_key and token == config.api_key:
        return True, None
    return False, None


def _extract_bearer(request: Request) -> str | None:
    auth = request.headers.get("Authorization") or request.headers.get("authorization")
    if not auth:
        return None
    parts = auth.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


async def require_api_token(request: Request) -> list[str] | None:
    """
    /api/* 鉴权依赖：返回该 token 允许的 chat_id 列表（None 表示不限）。

    - 未启用鉴权（本地非共享且未配凭证）→ 直接放行，返回 None
    - 启用鉴权但 token 缺失/非法 → 401
    """
    if not _auth_enabled():
        return None
    token = _extract_bearer(request)
    if not token:
        raise HTTPException(status_code=401, detail="缺少 Authorization Bearer Token")
    ok, allowed = _resolve_token_scope(token)
    if not ok:
        raise HTTPException(status_code=401, detail="API Token 无效")
    return allowed


def ensure_chat_id_allowed(allowed: list[str] | None, chat_id: str) -> None:
    """chat_id 白名单校验：allowed=None 不限制；否则 chat_id 必须在白名单内。"""
    if allowed is None:
        return
    if not chat_id:
        # 共享模式下空 chat_id 由上层（引擎/接口）单独拒绝；这里只在指定了
        # chat_id 时校验是否越权。
        return
    if chat_id not in allowed:
        raise HTTPException(
            status_code=403,
            detail=f"该 Token 无权向 chat_id={chat_id[:16]}... 发消息",
        )
