"""
DevCloud 服务主应用

运行方式:
    python -m devcloud_service.app
    # 或
    uvicorn devcloud_service.app:app --host 0.0.0.0 --port 8080
"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import config
from .storage import storage
from .handlers import callback, send, poll

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    logger.info("初始化存储...")
    await storage.init()
    logger.info(f"DevCloud 服务启动, 端口: {config.port}")
    
    yield
    
    # 关闭时
    logger.info("DevCloud 服务关闭")


# 创建 FastAPI 应用
app = FastAPI(
    title="HIL DevCloud Service",
    description="Human-in-the-Loop DevCloud 服务 - 企业微信消息代理",
    version="0.1.0",
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

# 注册路由
app.include_router(callback.router, tags=["callback"])
app.include_router(send.router, tags=["send"])
app.include_router(poll.router, tags=["poll"])


@app.get("/")
async def root():
    """根路径"""
    return {
        "service": "HIL DevCloud Service",
        "version": "0.1.0",
        "status": "running"
    }


@app.get("/health")
async def health():
    """健康检查"""
    return {"status": "healthy"}


def main():
    """主函数"""
    import uvicorn
    uvicorn.run(
        "devcloud_service.app:app",
        host="0.0.0.0",
        port=config.port,
        reload=True
    )


if __name__ == "__main__":
    main()
