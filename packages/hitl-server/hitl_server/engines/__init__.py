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
"""
from .base import BaseEngine
from .manager import engine_manager
from .ilink import ILinkEngine
from .wecom_aibot import WecomAibotEngine, WecomAibotStore
from .telegram import TelegramEngine, TelegramStore
from .discord import DiscordEngine, DiscordStore
from .feishu import FeishuEngine, FeishuStore

__all__ = [
    "BaseEngine",
    "engine_manager",
    "ILinkEngine",
    "WecomAibotEngine", "WecomAibotStore",
    "TelegramEngine", "TelegramStore",
    "DiscordEngine", "DiscordStore",
    "FeishuEngine", "FeishuStore",
]
