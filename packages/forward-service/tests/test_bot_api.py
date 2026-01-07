"""
Forward Service Bot 管理 API 单元测试

测试数据库模式下的 Bot CRUD 操作
"""
import pytest
import pytest_asyncio
import os
os.environ["USE_DATABASE"] = "true"

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from httpx import AsyncClient

from forward_service.app import app
from forward_service.database import get_db_manager
from forward_service.models import Base, Chatbot, ChatAccessRule
from forward_service.config_db import config_db


# ============== 测试 Fixtures ==============

@pytest_asyncio.fixture
async def test_db():
    """创建测试数据库"""
    # 使用内存 SQLite 数据库
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False
    )

    async_session_maker = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    # 创建所有表
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 注入到 database.py
    import forward_service.database
    original_get_session = forward_service.database._get_session

    def _test_get_session():
        return async_session_maker()

    forward_service.database._get_session = _test_get_session

    yield async_session_maker

    # 清理
    forward_service.database._get_session = original_get_session
    await engine.dispose()


@pytest_asyncio.fixture
async def test_client(test_db):
    """创建测试客户端"""
    # 初始化配置
    await config_db.initialize()

    # 使用 httpx 异步客户端
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client

    # 清理：删除所有数据
    async with test_db() as session:
        await session.execute("DELETE FROM chat_access_rules")
        await session.execute("DELETE FROM chatbots")
        await session.commit()


@pytest_asyncio.fixture
async def sample_bot(test_db):
    """创建示例 Bot"""
    async with test_db() as session:
        from forward_service.repository import get_chatbot_repository

        bot_repo = get_chatbot_repository(session)

        bot = await bot_repo.create(
            bot_key="test_bot",
            name="测试 Bot",
            url_template="https://api.example.com/agent/{agent_id}/message",
            agent_id="agent_123",
            api_key="key_456",
            timeout=60,
            access_mode="allow_all",
            description="用于测试的 Bot",
            enabled=True
        )

        await session.commit()

        # 重新获取以加载关联
        bot = await bot_repo.get_by_bot_key("test_bot")

    return bot


# ============== 模式检测 API 测试 ==============

def test_get_mode_database():
    """测试获取模式 API (数据库模式)"""
    from fastapi.testclient import TestClient
    client = TestClient(app)

    response = client.get("/admin/mode")

    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "database"
    assert data["supports_bot_api"] == True


# ============== Bot 列表 API 测试 ==============

@pytest.mark.asyncio
async def test_list_bots_empty(test_client):
    """测试获取空的 Bot 列表"""
    response = await test_client.get("/admin/bots")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] == True
    assert data["bots"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_list_bots_with_data(test_client, sample_bot):
    """测试获取 Bot 列表"""
    response = await test_client.get("/admin/bots")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] == True
    assert data["total"] == 1

    bots = data["bots"]
    assert len(bots) == 1
    assert bots[0]["bot_key"] == "test_bot"
    assert bots[0]["name"] == "测试 Bot"
    assert bots[0]["enabled"] == True
    assert bots[0]["whitelist_count"] == 0
    assert bots[0]["blacklist_count"] == 0


# ============== Bot 详情 API 测试 ==============

@pytest.mark.asyncio
async def test_get_bot_by_key(test_client, sample_bot):
    """测试获取单个 Bot 详情"""
    response = await test_client.get("/admin/bots/test_bot")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] == True

    bot = data["bot"]
    assert bot["bot_key"] == "test_bot"
    assert bot["name"] == "测试 Bot"
    assert bot["url_template"] == "https://api.example.com/agent/{agent_id}/message"
    assert bot["agent_id"] == "agent_123"
    assert bot["api_key"] == "key_456"
    assert bot["timeout"] == 60
    assert bot["access_mode"] == "allow_all"
    assert bot["enabled"] == True
    assert bot["whitelist"] == []
    assert bot["blacklist"] == []


@pytest.mark.asyncio
async def test_get_bot_not_found(test_client):
    """测试获取不存在的 Bot"""
    response = await test_client.get("/admin/bots/nonexistent")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] == False
    assert "不存在" in data["error"]


# ============== Bot 创建 API 测试 ==============

@pytest.mark.asyncio
async def test_create_bot_success(test_client):
    """测试成功创建 Bot"""
    bot_data = {
        "bot_key": "new_bot",
        "name": "新 Bot",
        "url_template": "https://api.example.com/test",
        "agent_id": "test_agent",
        "api_key": "test_key",
        "timeout": 30,
        "access_mode": "allow_all",
        "description": "测试创建",
        "enabled": True,
        "whitelist": [],
        "blacklist": []
    }

    response = await test_client.post("/admin/bots", json=bot_data)

    assert response.status_code == 200
    data = response.json()
    assert data["success"] == True
    assert data["bot"]["bot_key"] == "new_bot"
    assert data["bot"]["name"] == "新 Bot"


@pytest.mark.asyncio
async def test_create_bot_missing_required_field(test_client):
    """测试创建 Bot 缺少必填字段"""
    bot_data = {
        "bot_key": "incomplete_bot"
        # 缺少 name 和 url_template
    }

    response = await test_client.post("/admin/bots", json=bot_data)

    assert response.status_code == 200
    data = response.json()
    assert data["success"] == False
    assert "缺少必填字段" in data["error"]


@pytest.mark.asyncio
async def test_create_bot_duplicate_key(test_client, sample_bot):
    """测试创建重复 bot_key 的 Bot"""
    bot_data = {
        "bot_key": "test_bot",  # 已存在
        "name": "重复 Bot",
        "url_template": "https://api.example.com/test"
    }

    response = await test_client.post("/admin/bots", json=bot_data)

    assert response.status_code == 200
    data = response.json()
    assert data["success"] == False
    assert "已存在" in data["error"]


@pytest.mark.asyncio
async def test_create_bot_with_access_rules(test_client):
    """测试创建带访问规则的 Bot"""
    bot_data = {
        "bot_key": "whitelist_bot",
        "name": "白名单 Bot",
        "url_template": "https://api.example.com/test",
        "access_mode": "whitelist",
        "whitelist": ["chat_id_1", "chat_id_2"],
        "blacklist": []
    }

    response = await test_client.post("/admin/bots", json=bot_data)

    assert response.status_code == 200
    data = response.json()
    assert data["success"] == True

    bot = data["bot"]
    assert len(bot["whitelist"]) == 2
    assert bot["whitelist"][0]["chat_id"] == "chat_id_1"


# ============== Bot 更新 API 测试 ==============

@pytest.mark.asyncio
async def test_update_bot_success(test_client, sample_bot):
    """测试成功更新 Bot"""
    update_data = {
        "name": "更新后的名称",
        "description": "更新后的描述"
    }

    response = await test_client.put("/admin/bots/test_bot", json=update_data)

    assert response.status_code == 200
    data = response.json()
    assert data["success"] == True
    assert data["bot"]["name"] == "更新后的名称"
    assert data["bot"]["description"] == "更新后的描述"


@pytest.mark.asyncio
async def test_update_bot_not_found(test_client):
    """测试更新不存在的 Bot"""
    update_data = {
        "name": "新名称"
    }

    response = await test_client.put("/admin/bots/nonexistent", json=update_data)

    assert response.status_code == 200
    data = response.json()
    assert data["success"] == False
    assert "不存在" in data["error"]


@pytest.mark.asyncio
async def test_update_bot_access_rules(test_client, sample_bot):
    """测试更新 Bot 访问规则"""
    update_data = {
        "access_mode": "whitelist",
        "whitelist": ["chat_id_3", "chat_id_4"],
        "blacklist": []
    }

    response = await test_client.put("/admin/bots/test_bot", json=update_data)

    assert response.status_code == 200
    data = response.json()
    assert data["success"] == True

    bot = data["bot"]
    assert bot["access_mode"] == "whitelist"
    assert len(bot["whitelist"]) == 2
    assert bot["whitelist"][0]["chat_id"] == "chat_id_3"


# ============== Bot 删除 API 测试 ==============

@pytest.mark.asyncio
async def test_delete_bot_success(test_client, sample_bot):
    """测试成功删除 Bot"""
    response = await test_client.delete("/admin/bots/test_bot")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] == True

    # 验证已删除
    response = await test_client.get("/admin/bots/test_bot")
    assert response.json()["success"] == False


@pytest.mark.asyncio
async def test_delete_bot_not_found(test_client):
    """测试删除不存在的 Bot"""
    response = await test_client.delete("/admin/bots/nonexistent")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] == False
    assert "不存在" in data["error"]


# ============== JSON 模式兼容性测试 ==============

def test_json_mode_not_supported_for_bot_api(test_client):
    """测试 JSON 模式不支持 Bot API"""
    # 临时禁用数据库模式
    import forward_service.app
    original_use_database = forward_service.app.USE_DATABASE
    forward_service.app.USE_DATABASE = False

    try:
        response = test_client.get("/admin/bots")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] == False
        assert "JSON 模式不支持" in data["error"]
    finally:
        forward_service.app.USE_DATABASE = original_use_database


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
