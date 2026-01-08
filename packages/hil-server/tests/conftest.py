"""
HIL Server pytest 配置文件
"""
import sys
import os
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from contextlib import asynccontextmanager

# 将包目录添加到 Python 路径
pkg_root = Path(__file__).parent.parent
if str(pkg_root) not in sys.path:
    sys.path.insert(0, str(pkg_root))


# ============== 数据库测试 Fixtures ==============

@pytest_asyncio.fixture
async def test_db_engine():
    """创建测试数据库引擎"""
    from hil_server.models import Base
    
    # 使用内存 SQLite 数据库
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False
    )

    # 创建所有表
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # 清理
    await engine.dispose()


@pytest_asyncio.fixture
async def mock_db_manager(test_db_engine):
    """
    Mock 数据库管理器
    """
    import hil_server.database as db_module
    from hil_server.models import Base
    
    # 保存原始的 db_manager
    original_db_manager = db_module.db_manager
    
    # 创建测试用的 DatabaseManager
    class TestDatabaseManager:
        def __init__(self, engine):
            self._engine = engine
            self._session_factory = async_sessionmaker(
                bind=engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autocommit=False,
                autoflush=False,
            )
        
        @property
        def engine(self):
            return self._engine
        
        @property
        def session_factory(self):
            return self._session_factory
        
        @asynccontextmanager
        async def get_session(self):
            async with self._session_factory() as session:
                try:
                    yield session
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise
    
    # 替换全局 db_manager
    test_manager = TestDatabaseManager(test_db_engine)
    db_module.db_manager = test_manager
    
    yield test_manager
    
    # 恢复原始的 db_manager
    db_module.db_manager = original_db_manager


@pytest.fixture
def sample_session_data():
    """示例会话数据"""
    return {
        "session_id": "test-session-123",
        "chat_id": "test-chat-456",
        "message": "请确认是否继续？",
        "project_name": "test-project",
        "timeout": 300,
    }
