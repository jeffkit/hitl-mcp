"""
HIL Server 数据库管理模块

提供异步数据库操作支持
"""
import os
import logging
from pathlib import Path
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool

from .models import Base

logger = logging.getLogger(__name__)


def build_database_url() -> str:
    """
    构建数据库连接 URL
    
    支持环境变量:
    - HIL_DATABASE_URL: 完整的数据库 URL
    - HIL_DATABASE_PATH: SQLite 数据库文件路径
    """
    database_url = os.getenv("HIL_DATABASE_URL")
    if database_url:
        logger.info(f"使用环境变量 HIL_DATABASE_URL: {database_url[:30]}...")
        return database_url
    
    # 默认使用 SQLite
    db_path = os.getenv("HIL_DATABASE_PATH")
    if not db_path:
        # 默认路径: packages/hil-server/data/hil_server.db
        data_dir = Path(__file__).parent.parent / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        db_path = str(data_dir / "hil_server.db")
    
    database_url = f"sqlite+aiosqlite:///{db_path}"
    logger.info(f"使用 SQLite 数据库: {db_path}")
    return database_url


class DatabaseManager:
    """数据库管理器"""
    
    def __init__(self, database_url: str | None = None):
        self.database_url = database_url or build_database_url()
        self._engine = None
        self._session_factory = None
    
    async def init(self):
        """初始化数据库连接"""
        logger.info("正在初始化数据库...")
        
        # 配置引擎参数
        engine_kwargs = {
            "echo": os.getenv("HIL_DATABASE_ECHO", "").lower() in ("1", "true", "yes"),
        }
        
        # SQLite 特殊配置
        if self.database_url.startswith("sqlite"):
            engine_kwargs.update({
                "connect_args": {"check_same_thread": False},
            })
        
        self._engine = create_async_engine(self.database_url, **engine_kwargs)
        self._session_factory = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        
        # 创建表
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        logger.info("数据库初始化完成")
    
    async def close(self):
        """关闭数据库连接"""
        if self._engine:
            await self._engine.dispose()
            logger.info("数据库连接已关闭")
    
    @asynccontextmanager
    async def session(self):
        """获取数据库会话"""
        if not self._session_factory:
            raise RuntimeError("数据库未初始化")
        
        async with self._session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise


# 全局数据库管理器实例
_db_manager: DatabaseManager | None = None


async def init_database(database_url: str | None = None) -> DatabaseManager:
    """初始化全局数据库管理器"""
    global _db_manager
    _db_manager = DatabaseManager(database_url)
    await _db_manager.init()
    return _db_manager


async def close_database():
    """关闭全局数据库连接"""
    global _db_manager
    if _db_manager:
        await _db_manager.close()
        _db_manager = None


def get_db_manager() -> DatabaseManager:
    """获取全局数据库管理器"""
    if not _db_manager:
        raise RuntimeError("数据库未初始化，请先调用 init_database()")
    return _db_manager


@asynccontextmanager
async def database_lifespan():
    """数据库生命周期管理器（用于 FastAPI lifespan）"""
    await init_database()
    try:
        yield
    finally:
        await close_database()
