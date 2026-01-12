"""
Forward Service 主应用

接收企微机器人回调，转发到目标 URL，并将结果返回给用户。

运行方式:
    python -m forward_service.app
    # 或
    uvicorn forward_service.app:app --host 0.0.0.0 --port 8083

配置存储:
    - 默认使用 SQLite 数据库 (data/forward_service.db)
    - 支持 MySQL (通过 DATABASE_URL 环境变量配置)

并发配置:
    - FORWARD_WORKERS: Worker 进程数（默认 4）
    - MAX_CONCURRENT_REQUESTS: 每个进程的最大并发数（默认 10）
"""
import os
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .config import config
from .database import database_lifespan, get_db_manager
from .session_manager import init_session_manager
from .routes import admin_router, bots_router, callback_router

# 配置日志
# 为了调试 httpx 请求问题，暂时启用 DEBUG 级别
import os
log_level = logging.DEBUG if os.getenv("FORWARD_DEBUG") else logging.INFO
logging.basicConfig(
    level=log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# 设置 forwarder 模块的日志级别为 DEBUG（方便调试）
logging.getLogger("forward_service.services.forwarder").setLevel(logging.DEBUG)
logger = logging.getLogger(__name__)


# ============== 并发控制 ==============

# 全局并发限制（每个 worker 独立计数）
MAX_CONCURRENT_REQUESTS = int(os.getenv("MAX_CONCURRENT_REQUESTS", "10"))
_concurrent_requests = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
_active_requests = 0  # 当前活跃请求数（用于监控）


class ConcurrencyLimitMiddleware(BaseHTTPMiddleware):
    """并发限制中间件 - 防止请求过载"""

    async def dispatch(self, request: Request, call_next):
        global _active_requests

        # 只对 /callback 接口限流（管理接口不限制）
        if request.url.path == "/callback":
            # 检查是否达到并发上限
            if _concurrent_requests.locked():
                logger.warning(
                    f"⚠️ 达到并发上限 ({MAX_CONCURRENT_REQUESTS})，"
                    f"活跃请求: {_active_requests}，拒绝新请求"
                )
                return JSONResponse(
                    status_code=503,
                    content={
                        "errcode": 503,
                        "errmsg": "服务繁忙，请稍后重试"
                    }
                )

            # 获取信号量，处理请求
            async with _concurrent_requests:
                _active_requests += 1
                try:
                    response = await call_next(request)
                    return response
                finally:
                    _active_requests -= 1
        else:
            # 其他接口不限制
            return await call_next(request)


# ============== FastAPI 应用 ==============

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    async with database_lifespan():
        # 初始化配置
        await config.initialize()

        # 初始化会话管理器
        init_session_manager(get_db_manager())
        logger.info("  会话管理器已初始化")
        
        # 清理残留的 processing_sessions（服务重启时可能有未清理的记录）
        from .database import get_session
        from .models import ProcessingSession
        from sqlalchemy import delete
        
        async for db in get_session():
            result = await db.execute(delete(ProcessingSession))
            if result.rowcount > 0:
                logger.warning(f"  清理了 {result.rowcount} 条残留的 processing_sessions 记录")
            await db.commit()
            break

        # 验证配置
        errors = config.validate()
        if errors:
            for error in errors:
                logger.warning(f"配置警告: {error}")

        # 显示启动信息
        logger.info(f"🚀 Forward Service 启动 v3.1")
        logger.info(f"  端口: {config.port}")
        logger.info(f"  最大并发: {MAX_CONCURRENT_REQUESTS} 请求/进程")
        logger.info(f"  默认 Bot Key: {config.default_bot_key[:10]}..." if config.default_bot_key else "  默认 Bot Key: 未配置")
        logger.info(f"  Bot 数量: {len(config.bots)}")

        # 列出所有 Bot
        for bot_key, bot in config.bots.items():
            timeout = bot.forward_config.timeout or config.timeout
            logger.info(
                f"  - {bot.name} "
                f"(key={bot_key[:10]}..., "
                f"timeout={timeout}s, "
                f"enabled={bot.enabled})"
            )

        yield

        logger.info("Forward Service 关闭")


# 创建 FastAPI 应用
app = FastAPI(
    title="Forward Service",
    description="消息转发服务 - 接收企微回调，转发到 Agent",
    version="3.1.0",
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

# 🔥 并发限制中间件（必须在 CORS 之后注册）
app.add_middleware(ConcurrencyLimitMiddleware)

# 注册路由
app.include_router(admin_router)
app.include_router(bots_router)
app.include_router(callback_router)

# 静态文件目录
STATIC_DIR = Path(__file__).parent / "static"


# ============== 基础路由 ==============

@app.get("/")
async def root() -> dict:
    """根路径"""
    return {
        "service": "Forward Service",
        "version": "3.1.0",
        "status": "running",
        "max_concurrent": MAX_CONCURRENT_REQUESTS,
        "active_requests": _active_requests
    }


@app.get("/health")
async def health() -> dict:
    """健康检查"""
    errors = config.validate()
    return {
        "status": "healthy" if not errors else "unhealthy",
        "config_errors": errors,
        "default_bot_key": config.default_bot_key[:10] + "..." if config.default_bot_key else None,
        "bots_count": len(config.bots),
        "version": "3.1.0",
        "max_concurrent": MAX_CONCURRENT_REQUESTS,
        "active_requests": _active_requests
    }


# ============== 入口点 ==============

def main():
    """主函数 - 启动多进程 Uvicorn 服务器"""
    import uvicorn

    # 从环境变量读取 worker 数量
    workers = int(os.getenv("FORWARD_WORKERS", "4"))

    logger.info(f"🔥 启动 {workers} 个 Worker 进程")

    uvicorn.run(
        "forward_service.app:app",
        host="0.0.0.0",
        port=config.port,
        workers=workers,  # 🔥 多进程模式
        reload=False,
        log_level="info",
        # 性能优化配置
        backlog=2048,  # 连接队列大小
        timeout_keep_alive=5,  # Keep-Alive 超时
    )


if __name__ == "__main__":
    main()
