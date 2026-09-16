"""引擎注册表测试：注册 / 查询 / 通用动态启动端点 / entry point 加载。"""
import pytest

from hitl_server.engines import registry
from hitl_server.engines.base import BaseEngine
from hitl_server.engines.registry import EngineContext, EngineDescriptor


class FakeEngine(BaseEngine):
    def __init__(self, bot_key="fake-1", fail=False):
        super().__init__(worker_type="fake", bot_key=bot_key)
        self._running = False
        self._fail = fail

    async def start(self):
        if self._fail:
            raise RuntimeError("boom")
        self._running = True

    async def stop(self):
        self._running = False

    async def send_message(self, payload):
        return {"success": True}

    def status(self):
        return {"worker_type": self.worker_type, "bot_key": self.bot_key, "running": self._running}


@pytest.fixture(autouse=True)
def clean_registry():
    """每个用例拿到干净的注册表与引擎管理器（内置 descriptor 用例后恢复）。"""
    from hitl_server.engines import builtin, engine_manager

    registry.reset()
    for engine in list(engine_manager.all()):
        engine_manager.remove(engine.bot_key)
    for d in builtin.BUILTIN_DESCRIPTORS:
        registry.register(d)
    yield
    registry.reset()


@pytest.mark.asyncio
async def test_builtin_descriptors_registered():
    from hitl_server.engines import all_descriptors

    names = {d.name for d in all_descriptors()}
    assert {"ilink", "wecom-aibot", "telegram", "discord", "feishu"} <= names


@pytest.mark.asyncio
async def test_generic_start_endpoint_registers_and_starts():
    """通用 /admin/api/engines/{type}/start 对注册表中任意渠道可用。"""
    from hitl_server.handlers import admin

    async def build_startup(ctx):
        return None

    async def start(ctx, params):
        return FakeEngine(bot_key=params.get("bot_key", "fake-1"))

    registry.register(EngineDescriptor(
        name="fake", title="Fake", build_startup=build_startup, start=start,
    ))

    result = await admin._start_engine("fake", {"bot_key": "fake-9"})
    assert result["success"] is True
    assert result["engine"]["running"] is True

    from hitl_server.engines import engine_manager
    engine = engine_manager.get_by_bot_key("fake-9")
    assert engine is not None and engine.worker_type == "fake"


@pytest.mark.asyncio
async def test_start_engine_replaces_existing_instance():
    from hitl_server.handlers import admin
    from hitl_server.engines import engine_manager

    async def build_startup(ctx):
        return None

    async def start(ctx, params):
        return FakeEngine(bot_key=params.get("bot_key", "fake-1"))

    registry.register(EngineDescriptor(name="fake", title="Fake", build_startup=build_startup, start=start))

    await admin._start_engine("fake", {"bot_key": "fake-1"})
    first = engine_manager.get_by_bot_key("fake-1")
    await admin._start_engine("fake", {"bot_key": "fake-1"})
    second = engine_manager.get_by_bot_key("fake-1")
    assert first is not second
    assert engine_manager.status_all() and len(engine_manager.all()) == 1


@pytest.mark.asyncio
async def test_descriptor_failure_dict_passes_through():
    from hitl_server.handlers import admin

    async def build_startup(ctx):
        return None

    async def start(ctx, params):
        return {"success": False, "error": "缺少凭证"}

    registry.register(EngineDescriptor(name="fake", title="Fake", build_startup=build_startup, start=start))
    result = await admin._start_engine("fake", {})
    assert result == {"success": False, "error": "缺少凭证"}


@pytest.mark.asyncio
async def test_get_descriptor_unknown_returns_none():
    assert registry.get("no-such-channel") is None


@pytest.mark.asyncio
async def test_generic_stop_engine():
    from hitl_server.handlers import admin
    from hitl_server.engines import engine_manager

    async def build_startup(ctx):
        return None

    async def start(ctx, params):
        return FakeEngine(bot_key="fake-1")

    registry.register(EngineDescriptor(name="fake", title="Fake", build_startup=build_startup, start=start))
    await admin._start_engine("fake", {})
    result = await admin._stop_engine("fake", "fake-1")
    assert result["success"] is True
    assert engine_manager.get_by_bot_key("fake-1") is None
