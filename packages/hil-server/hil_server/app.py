"""
HIL Server 主应用 (Human-in-the-Loop Server)

运行方式:
    python -m hil_server.app
或:
    uvicorn hil_server.app:app --host 0.0.0.0 --port 8081
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .config import config
from .ws_manager import ws_manager
from .storage import storage
from .handlers import api_router, ws_router, admin_router, auth_router, forward_proxy_router

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
    
    # 初始化数据库（如果启用）
    from .storage import USE_DATABASE
    if USE_DATABASE:
        logger.info("  [数据库模式] 正在初始化数据库...")
        await storage.init_database()
        logger.info("  [数据库模式] 数据库初始化完成")
    else:
        logger.info("  [内存模式] 会话存储在内存中")
    
    # 启动心跳任务（Relay 模式需要）
    task = asyncio.create_task(heartbeat_task())
    
    # 启动内置引擎（in-process，启用时维持长连接，消息直接进 storage）
    from .engines import engine_manager, ILinkEngine
    if config.enable_ilink_engine:
        token_store_path = config.ilink_token_store_path or os.path.join(
            os.path.expanduser("~"), ".hil-mcp", "ilink_store.json"
        )
        ilink_engine = ILinkEngine(
            bot_key=config.ilink_bot_key,
            base_url=config.ilink_base_url,
            token_store_path=token_store_path,
            poll_timeout=config.ilink_poll_timeout,
        )
        ilink_engine.on_user_message = storage.handle_callback
        engine_manager.register(ilink_engine)
        logger.info(f"  [内置引擎] iLink 已启用: bot_key={config.ilink_bot_key}, base={config.ilink_base_url}")
    await engine_manager.start_all()
    
    # 启动文件清理任务（7 天后清理过期文件）
    from .file_storage import get_file_storage
    file_storage = get_file_storage()
    await file_storage.start_cleanup_task(interval_hours=24)
    logger.info("  [文件清理] 已启动定期清理任务（每 24 小时）")
    
    yield
    
    # 停止心跳任务
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    
    # 停止内置引擎
    from .engines import engine_manager
    await engine_manager.stop_all()
    
    # 停止文件清理任务
    file_storage.stop_cleanup_task()
    
    # 关闭数据库连接
    if USE_DATABASE:
        from .database import close_database
        await close_database()
    
    logger.info("HIL Server 关闭")


# 创建 FastAPI 应用
# 注意：docs_url 设为 None，因为 /docs 被自定义路由使用（返回网页文档）
app = FastAPI(
    title="HIL Server",
    description="Human-in-the-Loop Server - 支持 Relay 和 Direct 两种模式",
    version="2.0.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None
)

# 注册路由
app.include_router(api_router)
app.include_router(ws_router)
app.include_router(admin_router)
app.include_router(auth_router)
app.include_router(forward_proxy_router)

# 查找仓库根目录（兼容不同部署结构）
# - monorepo: packages/hil-server/hil_server/app.py -> 需要 4 层 parent
# - dev 服务器: hil_server/app.py -> 需要 2 层 parent
def find_repo_root():
    """查找包含 website 目录的根路径"""
    current = Path(__file__).parent
    for _ in range(5):  # 最多往上找 5 层
        current = current.parent
        if (current / "website").exists():
            return current
    # 回退到默认
    return Path(__file__).parent.parent.parent.parent

REPO_ROOT = find_repo_root()

# 挂载静态文件（website 在仓库根目录）
website_dir = REPO_ROOT / "website"
if website_dir.exists():
    static_dir = website_dir / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# 挂载文件存储目录（用于单聊超长消息文件链接）
file_storage_dir = Path(os.getenv("FILE_STORAGE_DIR", "/data/projects/hitl/static/files"))
if file_storage_dir.exists():
    app.mount("/files", StaticFiles(directory=str(file_storage_dir)), name="files")
    logger.info(f"挂载文件存储目录: /files -> {file_storage_dir}")
else:
    logger.warning(f"文件存储目录不存在: {file_storage_dir}")

# 挂载新版管理台（React）
console_dir = Path(__file__).parent / "console" / "dist"
if console_dir.exists():
    app.mount("/console/assets", StaticFiles(directory=str(console_dir / "assets")), name="console-assets")


@app.get("/")
async def root():
    """根路径 - 返回首页"""
    website_dir = REPO_ROOT / "website"
    index_file = website_dir / "index.html"
    
    if index_file.exists():
        return FileResponse(str(index_file))
    
    # 如果首页不存在，返回 API 信息
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


@app.get("/console/{path:path}")
@app.get("/console")
async def console_spa(path: str = ""):
    """新版管理台（React SPA）- 所有路由返回 index.html"""
    console_dir = Path(__file__).parent / "console" / "dist"
    index_file = console_dir / "index.html"
    
    if index_file.exists():
        return FileResponse(str(index_file))
    
    return {"error": "Console not found. Run 'pnpm build' in hil_server/console/"}


@app.get("/docs")
async def docs_page():
    """文档页面"""
    website_dir = REPO_ROOT / "website"
    docs_file = website_dir / "docs.html"
    
    if docs_file.exists():
        return FileResponse(str(docs_file))
    
    return {"error": "Documentation not found"}


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
