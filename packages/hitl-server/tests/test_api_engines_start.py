"""通用 /api/engines/{etype}/start 端点回归测试。

背景（2026-10 修复）：TS 客户端（telegram/discord/feishu/generic）按约定
调用 /api/engines/{type}/start，但 /api 面此前只有 wecom-aibot 特例，
其余渠道 404、自动注册静默失败。本文件守住两件事：

1. 通用路由存在且对注册表中任意渠道可用（直调 handler，不起真引擎）；
2. wecom-aibot 特例路由仍注册在通用路由之前（FastAPI 按注册顺序匹配，
   特例语义不被通用路由遮蔽）。
"""

from __future__ import annotations

import pytest

from hitl_server.engines import registry
from hitl_server.engines.base import BaseEngine
from hitl_server.engines.registry import EngineDescriptor


class FakeEngine(BaseEngine):
    def __init__(self, bot_key="fake-1"):
        super().__init__(worker_type="fake", bot_key=bot_key)
        self._running = True

    async def start(self):
        self._running = True

    async def stop(self):
        self._running = False

    async def send_message(self, payload):
        return {"success": True}

    def status(self):
        return {"worker_type": self.worker_type, "bot_key": self.bot_key, "running": self._running}


@pytest.fixture(autouse=True)
def clean_registry():
    from hitl_server.engines import builtin, engine_manager

    registry.reset()
    for engine in list(engine_manager.all()):
        engine_manager.remove(engine.bot_key)
    for d in builtin.BUILTIN_DESCRIPTORS:
        registry.register(d)
    yield
    registry.reset()


class _FakeRequest:
    """handler 只用到 await request.json()，无需构造真实 Request。"""

    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_api_generic_start_route_dispatches():
    """/api/engines/{etype}/start 对注册表中的自定义渠道可用（原 404 场景）。"""
    from hitl_server.handlers import api

    async def build_startup(ctx):
        return None

    async def start(ctx, params):
        return FakeEngine(bot_key=params.get("bot_key", "fake-1"))

    registry.register(
        EngineDescriptor(name="fake", title="Fake", build_startup=build_startup, start=start)
    )

    result = await api.engines_generic_start("fake", _FakeRequest({"bot_key": "fake-9"}))
    assert result["success"] is True
    assert result["engine"]["running"] is True

    from hitl_server.engines import engine_manager
    assert engine_manager.get_by_bot_key("fake-9") is not None


@pytest.mark.asyncio
async def test_api_generic_start_unknown_engine_404():
    from fastapi import HTTPException
    from hitl_server.handlers import api

    with pytest.raises(HTTPException) as exc:
        await api.engines_generic_start("no-such-channel", _FakeRequest({}))
    assert exc.value.status_code == 404


def test_wecom_specific_route_registered_before_generic():
    """wecom-aibot 特例必须先于通用路由注册（FastAPI 按注册顺序匹配）。"""
    from hitl_server.handlers import api

    paths = [getattr(r, "path", "") for r in api.router.routes]
    assert "/api/engines/wecom-aibot/start" in paths
    assert "/api/engines/{etype}/start" in paths
    assert paths.index("/api/engines/wecom-aibot/start") < paths.index(
        "/api/engines/{etype}/start"
    )
