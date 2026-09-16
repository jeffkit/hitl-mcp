"""HITL Server 内置引擎。

把长连接（iLink 长轮询 / wecom-aibot WS / Telegram / Discord / Feishu）收敛进
HITL Server 进程内作为内置引擎直接运行：

- 收到上游用户消息 → 进程内直接调 storage.handle_callback（不走 WS）
- /api/send 命中内置引擎 → 进程内直接调 engine.send_message（不走 WS）
- /api/ilink/* → 直接调内置 ilink 引擎

渠道一览：
  ilink       — 个人微信（ClawBot / iLink）HTTP 长轮询
  wecom-aibot — 企业微信 AI 机器人 WebSocket
  telegram    — Telegram Bot API 长轮询
  discord     — Discord Gateway WebSocket
  feishu      — 飞书企业自建应用 WebSocket（需 lark-oapi）

插件化：app.py / admin.py 不再硬编码渠道清单，而是面向
``registry.EngineDescriptor`` 编排（见 ``builtin.py`` 与 docs/engine-plugins.md）。
新增内置渠道在 ``builtin.BUILTIN_DESCRIPTORS`` 追加；外置渠道用 entry point 组
``hitl_server.engines`` 注册，无需改核心。
"""
from .base import BaseEngine
from .manager import engine_manager
from .registry import (
    EngineContext,
    EngineDescriptor,
    all_descriptors,
    maybe_await,
    get as get_descriptor,
    register as register_descriptor,
)
from .ilink import ILinkEngine
from .wecom_aibot import WecomAibotEngine, WecomAibotStore
from .telegram import TelegramEngine, TelegramStore
from .discord import DiscordEngine, DiscordStore
from .feishu import FeishuEngine, FeishuStore
from .builtin import BUILTIN_DESCRIPTORS

for _descriptor in BUILTIN_DESCRIPTORS:
    register_descriptor(_descriptor)

__all__ = [
    "BaseEngine",
    "engine_manager",
    "EngineContext",
    "EngineDescriptor",
    "all_descriptors",
    "maybe_await",
    "get_descriptor",
    "register_descriptor",
    "BUILTIN_DESCRIPTORS",
    "ILinkEngine",
    "WecomAibotEngine", "WecomAibotStore",
    "TelegramEngine", "TelegramStore",
    "DiscordEngine", "DiscordStore",
    "FeishuEngine", "FeishuStore",
]
