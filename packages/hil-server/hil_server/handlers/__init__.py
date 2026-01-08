"""
Relay Server Handlers
"""
from .api import router as api_router
from .websocket import router as ws_router
from .admin import router as admin_router
from .auth import router as auth_router
from .forward_proxy import router as forward_proxy_router

__all__ = [
    "api_router",
    "ws_router", 
    "admin_router",
    "auth_router",
    "forward_proxy_router"
]
