"""
测试 Forward Service 数据库集成

测试:
1. 使用数据库配置启动服务
2. API 接口正常工作
3. 配置更新功能
"""
import pytest
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from forward_service.database import init_database, close_database, get_db_manager
from forward_service.config_db import ConfigDB, BotConfig, ForwardConfig, AccessControl
from forward_service.models import Base, Chatbot


@pytest.mark.asyncio
async def test_database_config_initialization():
    """测试数据库配置初始化"""
    # 创建内存数据库
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # 创建表
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 初始化配置
    config = ConfigDB()

    # 添加测试数据
    async_session = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session() as session:
        from forward_service.repository import get_chatbot_repository, get_access_rule_repository

        bot_repo = get_chatbot_repository(session)
        rule_repo = get_access_rule_repository(session)

        # 创建测试 Bot
        bot1 = await bot_repo.create(
            bot_key="test_bot_1",
            name="测试 Bot 1",
            url_template="https://api1.com",
            access_mode="allow_all",
            enabled=True
        )

        await rule_repo.create(bot1.id, "user1", "whitelist")

        bot2 = await bot_repo.create(
            bot_key="test_bot_2",
            name="测试 Bot 2",
            url_template="https://api2.com",
            access_mode="whitelist",
            enabled=True
        )

        await rule_repo.set_whitelist(bot2.id, ["user2", "user3"])

    # 模拟数据库连接
    import forward_service.database as db_module
    from forward_service.database import DatabaseManager

    # 创建真正的数据库管理器
    db_manager = DatabaseManager("sqlite+aiosqlite:///:memory:")
    db_manager.init_engine()  # 不是异步的
    db_manager._engine = engine  # 使用我们创建的 engine
    db_manager.init_session_factory()

    # 设置全局 db_manager
    original_db_manager = db_module.db_manager
    db_module.db_manager = db_manager

    original_get_manager = db_module.get_db_manager

    try:
        # get_db_manager 现在应该返回我们的 manager
        db_module.get_db_manager = lambda: db_manager

        # 初始化配置
        await config.initialize()

        # 调试
        print(f"加载的 bots: {list(config.bots.keys())}")

        # 验证配置
        assert len(config.bots) == 2, f"期望 2 个 bots,实际 {len(config.bots)}"
        assert "test_bot_1" in config.bots
        assert "test_bot_2" in config.bots

        # 测试 get_bot
        bot = config.get_bot("test_bot_1")
        assert bot is not None
        assert bot.name == "测试 Bot 1"
        assert bot.forward_config.url_template == "https://api1.com"

        # 测试访问控制
        allowed, reason = config.check_access(bot, "user1")
        # bot1 是 allow_all 模式
        assert allowed is True

        bot2 = config.get_bot("test_bot_2")
        allowed, reason = config.check_access(bot2, "user2")
        # bot2 是 whitelist 模式, user2 在白名单中
        assert allowed is True

        allowed, reason = config.check_access(bot2, "user4")
        # bot2 是 whitelist 模式, user4 不在白名单中
        assert allowed is False
        assert "白名单" in reason

        print("✅ 数据库配置初始化测试通过")

    finally:
        db_module.get_db_manager = original_get_manager
        db_module.db_manager = original_db_manager
        await engine.dispose()


@pytest.mark.asyncio
async def test_config_dict_serialization():
    """测试配置序列化"""
    # 创建测试配置
    bot_config = BotConfig(
        bot_key="test_key",
        name="测试 Bot",
        description="测试描述",
        forward_config=ForwardConfig(
            url_template="https://api.com",
            agent_id="agent-001",
            api_key="sk-test",
            timeout=30
        ),
        access_control=AccessControl(
            mode="whitelist",
            whitelist=["user1", "user2"],
            blacklist=["bad_user"]
        ),
        enabled=True
    )

    # 转换为字典
    data = bot_config.to_dict()

    assert data["bot_key"] == "test_key"
    assert data["name"] == "测试 Bot"
    assert data["forward_config"]["url_template"] == "https://api.com"
    assert data["forward_config"]["agent_id"] == "agent-001"
    assert data["access_control"]["mode"] == "whitelist"
    assert set(data["access_control"]["whitelist"]) == {"user1", "user2"}
    assert data["access_control"]["blacklist"] == ["bad_user"]

    print("✅ 配置序列化测试通过")


if __name__ == "__main__":
    print("运行数据库集成测试...\n")

    asyncio.run(test_database_config_initialization())
    asyncio.run(test_config_dict_serialization())

    print("\n✅ 所有测试通过!")
