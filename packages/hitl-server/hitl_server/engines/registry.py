"""内置引擎注册表：渠道插件化注册。

新增 IM 渠道不再需要修改 app.py / admin.py / engines/__init__.py 核心：

1. 实现一个 ``BaseEngine`` 子类（插件接口：``start`` / ``stop`` /
   ``send_message`` / ``status`` + ``on_user_message`` 回调）。
2. 在同模块里构造一个 :class:`EngineDescriptor`，提供两个装配钩子：
   - ``build_startup(ctx)`` — 服务启动时按 env / 持久化凭证自动装配（可返回 None）；
   - ``start(ctx, params)`` — 管理台 ``POST /api/engines/{name}/start`` 动态拉起。
3. 注册方式二选一：
   - 内置渠道：在 ``engines/__init__.py`` 的 ``BUILTIN_DESCRIPTORS`` 里追加；
   - 外置插件：打包成 wheel 并声明 entry point 组 ``hitl_server.engines``，
     值指向 descriptor 实例（或返回 descriptor 的模块/工厂）。

核心（app.py lifespan / admin.py 通用路由）只面向 descriptor 编排，
不含任何 IM 渠道特有逻辑。
"""
import logging
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import Any, Awaitable, Callable, Dict, List, Optional

from .base import BaseEngine

logger = logging.getLogger(__name__)

#: 外置插件的 entry point 组名
ENTRY_POINT_GROUP = "hitl_server.engines"


@dataclass
class EngineContext:
    """装配引擎时可用的核心服务。"""

    #: HITLConfig（pydantic-settings），渠道自行读取自己的 env 字段
    config: Any
    #: storage 单例（engine.on_user_message 接 storage.handle_callback）
    storage: Any


# 装配钩子签名
StartupBuilder = Callable[[EngineContext], Awaitable[Optional[BaseEngine]]]
DynamicStarter = Callable[[EngineContext, Dict[str, Any]], Awaitable[BaseEngine]]


@dataclass
class EngineDescriptor:
    """一个 IM 渠道的注册单元。"""

    #: worker_type（如 "telegram"），与 BaseEngine.worker_type 一致
    name: str
    #: 人读显示名（日志/文档用）
    title: str
    #: 启动时自动装配（env / 持久化凭证）；返回 None 表示本渠道未启用
    build_startup: StartupBuilder
    #: 管理台动态启动。params 是请求体 dict（经 request_model 校验后）。
    #: 实现应自行完成「替换已有实例 → 落盘凭证 → 构造 → 注册 → start」。
    start: DynamicStarter
    #: start 请求体的 pydantic 模型（None 则原样透传 dict）
    request_model: Optional[type] = None
    #: 渠道凭证字段名（文档/通用客户端提示用，如 ["bot_token"]）
    credentials: List[str] = field(default_factory=list)
    #: 渠道特有路由（如 ilink 的 qr/status），追加到 admin router
    extra_routes: Optional[Callable[[Any], None]] = None
    #: 来源：builtin / entry point 模块名（诊断用）
    source: str = "builtin"


_REGISTRY: Dict[str, EngineDescriptor] = {}
#: entry point 是否已加载（进程内一次）
_ENTRY_POINTS_LOADED = False


def register(descriptor: EngineDescriptor) -> None:
    """注册（或替换）一个渠道 descriptor。"""
    _REGISTRY[descriptor.name] = descriptor


def get(name: str) -> Optional[EngineDescriptor]:
    """按 worker_type 查 descriptor（含懒加载 entry point 插件）。"""
    _load_entry_points_once()
    return _REGISTRY.get(name)


def all_descriptors() -> List[EngineDescriptor]:
    """全部已注册 descriptor（内置 + entry point 插件），按名字排序。"""
    _load_entry_points_once()
    return [_REGISTRY[k] for k in sorted(_REGISTRY)]


def _load_entry_points_once() -> None:
    global _ENTRY_POINTS_LOADED
    if _ENTRY_POINTS_LOADED:
        return
    _ENTRY_POINTS_LOADED = True
    try:
        eps = entry_points(group=ENTRY_POINT_GROUP)
    except TypeError:  # pragma: no cover - Python 3.9 兼容
        eps = entry_points().get(ENTRY_POINT_GROUP, [])  # type: ignore[union-attr]
    for ep in eps:
        try:
            obj = ep.load()
            descriptor = obj() if callable(obj) and not isinstance(obj, EngineDescriptor) else obj
            if not isinstance(descriptor, EngineDescriptor):
                raise TypeError(f"expected EngineDescriptor, got {type(descriptor)!r}")
            descriptor.source = f"entry-point:{ep.value}"
            register(descriptor)
            logger.info(f"已加载外置引擎插件: {descriptor.name} ({descriptor.source})")
        except Exception:
            logger.error(f"加载引擎插件 {ep.name} 失败:", exc_info=True)


def reset() -> None:
    """清空注册表并重置 entry point 加载标记（仅测试用）。"""
    global _ENTRY_POINTS_LOADED
    _REGISTRY.clear()
    _ENTRY_POINTS_LOADED = False
