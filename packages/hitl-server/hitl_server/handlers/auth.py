"""
认证 API 处理器

处理管理台登录、Token 验证
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

import jwt
from fastapi import APIRouter, HTTPException, Depends
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
