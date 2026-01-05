"""
HIL Server 主应用 (Human-in-the-Loop Server)

运行方式:
    python -m hil_server.app
或:
    uvicorn hil_server.app:app --host 0.0.0.0 --port 8081
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import config
from .ws_manager import ws_manager
from .storage import storage
from .handlers import api_router, ws_router

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def heartbeat_task():
    """心跳任务"""
    while True:
        try:
            await asyncio.sleep(config.heartbeat_interval)
            await ws_manager.broadcast_ping()
            await ws_manager.check_heartbeat()
            await storage.cleanup_expired()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"心跳任务错误: {e}", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    mode = config.effective_mode
    logger.info(f"HIL Server 启动")
    logger.info(f"  端口: {config.port}")
    logger.info(f"  模式: {mode}")
    
    if mode == "direct":
        logger.info(f"  [Direct 模式] 直接调用 fly-pigeon")
        logger.info(f"  回调地址: http://localhost:{config.port}/api/callback")
    else:
        logger.info(f"  [Relay 模式] 等待 Worker 连接")
    
    # 启动心跳任务（Relay 模式需要）
    task = asyncio.create_task(heartbeat_task())
    
    yield
    
    # 停止心跳任务
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    
    logger.info("HIL Server 关闭")


# 创建 FastAPI 应用
app = FastAPI(
    title="HIL Server",
    description="Human-in-the-Loop Server - 支持 Relay 和 Direct 两种模式",
    version="2.0.0",
    lifespan=lifespan
)

# 注册路由
app.include_router(api_router)
app.include_router(ws_router)


@app.get("/")
async def root():
    """根路径"""
    mode = config.effective_mode
    result = {
        "service": "HIL Server",
        "version": "2.0.0",
        "status": "running",
        "mode": mode,
    }
    
    if mode == "relay":
        result["worker_connected"] = ws_manager.has_worker
    
    return result


@app.get("/health")
async def health():
    """健康检查"""
    mode = config.effective_mode
    result = {
        "status": "healthy",
        "mode": mode,
    }
    
    if mode == "relay":
        result["worker_connected"] = ws_manager.has_worker
        result["worker_count"] = len(ws_manager._workers)
    
    return result


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "hil_server.app:app",
        host=config.host,
        port=config.port,
        reload=False,
        # 禁用 uvicorn 的 WebSocket keepalive ping
        # 因为通过 nginx 代理时，协议级 ping 会导致 keepalive ping timeout
        # 我们使用应用层的心跳机制来保持连接
        ws_ping_interval=None,
        ws_ping_timeout=None,
    )
