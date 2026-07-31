"""Discord Gateway WebSocket 内置引擎。

通过 Discord Gateway WebSocket 接收 MESSAGE_CREATE 事件，REST API 发消息：
- 收到消息 → 转 fly-pigeon 兼容结构 → storage.handle_callback
- 发送时带 [#short_id] 头，支持 message_reference 引用回复

Gateway 实现细节：
- Opcode 10 Hello：开始心跳 (heartbeat_interval)
- Opcode 2 Identify：鉴权，启用 GUILDS + GUILD_MESSAGES + MESSAGE_CONTENT + DIRECT_MESSAGES 意图
- Opcode 11 Heartbeat ACK：记录 ACK 状态
- Opcode 0 Dispatch：处理 READY 和 MESSAGE_CREATE 事件
- Opcode 7/9：重连 / 重新 Identify

Short-ID 匹配优先级：
1. referenced_message.content 中提取 [#short_id]（引用回复精确匹配）
2. 消息文本中直接含 [#short_id]

凭证：bot_token 存入 ~/.hil-mcp/discord_store.json
管理台：POST /admin/api/engines/discord/start  { bot_token, bot_key }
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import time
from typing import Optional

import httpx
import websockets
from websockets.exceptions import ConnectionClosedError

from .base import BaseEngine

logger = logging.getLogger(__name__)

_SHORT_ID_RE = re.compile(r'\[#([a-f0-9]{8,12})(?:\s+[^\]]+)?\]')
DISCORD_API = "https://discord.com/api/v10"
DISCORD_WS_URL = "wss://gateway.discord.gg/?v=10&encoding=json"

# Gateway opcodes
OP_DISPATCH    = 0
OP_HEARTBEAT   = 1
OP_IDENTIFY    = 2
OP_RESUME      = 6
OP_RECONNECT   = 7
OP_INVALID_SESSION = 9
OP_HELLO       = 10
OP_HEARTBEAT_ACK = 11

# Intents (bitfield)
INTENT_GUILDS            = 1 << 0
INTENT_GUILD_MESSAGES    = 1 << 9
INTENT_MESSAGE_CONTENT   = 1 << 15   # privileged — must be enabled in Bot settings
INTENT_DIRECT_MESSAGES   = 1 << 12
INTENTS = INTENT_GUILDS | INTENT_GUILD_MESSAGES | INTENT_MESSAGE_CONTENT | INTENT_DIRECT_MESSAGES


# ── 凭证持久化 ─────────────────────────────────────────────────────────────────

class DiscordStore:
    """Discord 凭证持久化（JSON 文件，线程安全）。"""

    def __init__(self, path: str):
        self.path = path
        self._data: dict = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except Exception:
                self._data = {}

    def _save(self) -> None:
        d = os.path.dirname(self.path)
        if d:
            os.makedirs(d, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def get_token(self) -> Optional[str]:
        with self._lock:
            return self._data.get("bot_token")

    def set_token(self, token: str) -> None:
        with self._lock:
            self._data["bot_token"] = token
            self._save()

    def clear(self) -> None:
        with self._lock:
            self._data = {}
            self._save()


# ── 辅助函数 ───────────────────────────────────────────────────────────────────

def _extract_short_id(text: str) -> Optional[str]:
    m = _SHORT_ID_RE.search(text or "")
    return m.group(1) if m else None


def _to_callback_data(event: dict) -> Optional[dict]:
    """Discord MESSAGE_CREATE → fly-pigeon callback_data。"""
    author = event.get("author") or {}
    if author.get("bot"):
        return None  # 忽略 Bot 自身的消息

    content = event.get("content") or ""
    if not content.strip():
        return None

    channel_id = str(event.get("channel_id") or "")
    user_id = str(author.get("id") or "")
    name = author.get("username") or author.get("global_name") or ""

    data: dict = {
        "chatid": channel_id,
        "chattype": "single" if event.get("guild_id") is None else "group",
        "msgtype": "text",
        "text": {"content": content},
        "from": {"userid": user_id, "name": name},
        "raw_discord_event": event,
    }

    # Short-ID：引用回复优先
    ref_msg = event.get("referenced_message")
    if ref_msg:
        ref_content = ref_msg.get("content") or ""
        sid = _extract_short_id(ref_content)
        if sid:
            data["short_id"] = sid
        if ref_content:
            data["quote"] = {"msgtype": "text", "text": {"content": ref_content}}

    # 当前消息文本中含 [#short_id]
    if "short_id" not in data:
        sid = _extract_short_id(content)
        if sid:
            data["short_id"] = sid

    return data


def _format_message(message: str, short_id: str, project_name: Optional[str], wait_reply: bool) -> str:
    parts: list[str] = []
    if short_id:
        parts.append(f"[#{short_id} {project_name}]" if project_name else f"[#{short_id}]")
    parts.append(message)
    body = "\n".join(parts)
    if wait_reply:
        body = f"{body}\n\n> 请引用回复此消息以便系统自动关联"
    return body


# ── Gateway 客户端 ─────────────────────────────────────────────────────────────

class DiscordEngine(BaseEngine):
    """Discord Gateway WebSocket 内置引擎。"""

    WORKER_TYPE = "discord"

    def __init__(self, bot_key: str, bot_token: str, store: DiscordStore):
        super().__init__(worker_type=self.WORKER_TYPE, bot_key=bot_key)
        self._token = bot_token
        self._store = store
        self._running = False
        self._connected = False
        self._http: Optional[httpx.AsyncClient] = None
        self._ws_task: Optional[asyncio.Task] = None
        # Gateway session state
        self._session_id: Optional[str] = None
        self._resume_url: Optional[str] = None
        self._seq: Optional[int] = None
        self._heartbeat_interval: float = 41.25
        self._last_ack: float = 0.0
        self._bot_id: Optional[str] = None
        # Sent message cache: channel_id → message_id (for reply threading)
        self._last_sent: dict[str, str] = {}

    def _headers(self) -> dict:
        return {"Authorization": f"Bot {self._token}"}

    async def start(self) -> None:
        self._http = httpx.AsyncClient(timeout=15)
        self._running = True
        self._ws_task = asyncio.create_task(self._gateway_loop())
        logger.info(f"[discord-engine] 已启动 (bot_key={self.bot_key})")

    async def stop(self) -> None:
        self._running = False
        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
        if self._http:
            await self._http.aclose()
            self._http = None
        self._connected = False
        logger.info(f"[discord-engine] 已停止 (bot_key={self.bot_key})")

    # ── Gateway loop ──────────────────────────────────────────────────────────

    async def _gateway_loop(self) -> None:
        retry_delay = 5.0
        while self._running:
            ws_url = (self._resume_url or DISCORD_WS_URL) + "?v=10&encoding=json"
            try:
                async with websockets.connect(ws_url, max_size=10 * 1024 * 1024) as ws:
                    self._connected = True
                    logger.info(f"[discord-engine] WebSocket 已连接: {ws_url}")
                    await self._run_session(ws)
            except ConnectionClosedError as e:
                logger.warning(f"[discord-engine] WebSocket 断开: {e}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[discord-engine] Gateway 异常: {e}", exc_info=True)
            finally:
                self._connected = False

            if not self._running:
                break
            logger.info(f"[discord-engine] {retry_delay}s 后重连")
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 1.5, 60)

    async def _run_session(self, ws) -> None:
        hb_task: Optional[asyncio.Task] = None
        try:
            async for raw in ws:
                msg = json.loads(raw)
                op = msg.get("op")
                d  = msg.get("d")
                s  = msg.get("s")
                t  = msg.get("t")

                if s is not None:
                    self._seq = s

                if op == OP_HELLO:
                    self._heartbeat_interval = d["heartbeat_interval"] / 1000
                    hb_task = asyncio.create_task(self._heartbeat_loop(ws))
                    if self._session_id and self._seq is not None:
                        await ws.send(json.dumps({
                            "op": OP_RESUME,
                            "d": {"token": self._token, "session_id": self._session_id, "seq": self._seq},
                        }))
                        logger.info(f"[discord-engine] RESUME session={self._session_id}")
                    else:
                        await ws.send(json.dumps({
                            "op": OP_IDENTIFY,
                            "d": {
                                "token": self._token,
                                "intents": INTENTS,
                                "properties": {"os": "linux", "browser": "hil-mcp", "device": "hil-mcp"},
                            },
                        }))
                        logger.info("[discord-engine] IDENTIFY sent")

                elif op == OP_HEARTBEAT_ACK:
                    self._last_ack = time.time()

                elif op == OP_HEARTBEAT:
                    await ws.send(json.dumps({"op": OP_HEARTBEAT, "d": self._seq}))

                elif op == OP_RECONNECT:
                    logger.info("[discord-engine] 收到 RECONNECT，重连中")
                    break

                elif op == OP_INVALID_SESSION:
                    logger.warning(f"[discord-engine] INVALID_SESSION resumable={d}")
                    if not d:  # not resumable
                        self._session_id = None
                        self._seq = None
                    await asyncio.sleep(5)
                    break

                elif op == OP_DISPATCH:
                    await self._handle_dispatch(t, d)
        finally:
            if hb_task:
                hb_task.cancel()

    async def _heartbeat_loop(self, ws) -> None:
        while True:
            await asyncio.sleep(self._heartbeat_interval)
            try:
                await ws.send(json.dumps({"op": OP_HEARTBEAT, "d": self._seq}))
            except Exception:
                break

    async def _handle_dispatch(self, t: str, d: dict) -> None:
        if t == "READY":
            self._session_id = d.get("session_id")
            self._resume_url = d.get("resume_gateway_url")
            self._bot_id = (d.get("user") or {}).get("id")
            logger.info(f"[discord-engine] READY bot_id={self._bot_id} session={self._session_id}")
            return

        if t == "MESSAGE_CREATE":
            # Skip own messages
            author_id = str((d.get("author") or {}).get("id") or "")
            if author_id == self._bot_id:
                return
            cb = _to_callback_data(d)
            if not cb:
                return
            logger.info(
                f"[discord-engine] 消息: channel={cb['chatid']} "
                f"text={cb['text']['content'][:60]!r}"
            )
            if self.on_user_message:
                try:
                    result = await self.on_user_message(cb)
                    if isinstance(result, dict) and result.get("prompt_user"):
                        waiting_ids = result.get("waiting_short_ids", [])
                        prompt = (
                            f"⚠️ 有 {len(waiting_ids)} 条待回复，请引用对应消息以匹配：\n"
                            + "\n".join(f"  [#{sid}]" for sid in waiting_ids)
                        )
                        await self._send_raw(cb["chatid"], prompt)
                except Exception as e:
                    logger.error(f"[discord-engine] 处理消息失败: {e}", exc_info=True)

    # ── 发消息 ────────────────────────────────────────────────────────────────

    async def _send_raw(self, channel_id: str, content: str,
                        reference_message_id: Optional[str] = None) -> Optional[str]:
        payload: dict = {"content": content}
        if reference_message_id:
            payload["message_reference"] = {"message_id": reference_message_id}
        try:
            resp = await self._http.post(
                f"{DISCORD_API}/channels/{channel_id}/messages",
                headers=self._headers(),
                json=payload,
            )
            if not resp.is_success:
                logger.warning(f"[discord-engine] 发送失败: {resp.status_code} {resp.text[:200]}")
                return None
            data = resp.json()
            return str(data.get("id") or "")
        except Exception as e:
            logger.error(f"[discord-engine] 发送异常: {e}")
            return None

    async def send_message(self, payload: dict) -> dict:
        channel_id = str(payload.get("chat_id") or "")
        message = payload.get("message") or ""
        short_id = payload.get("short_id") or ""
        project_name = payload.get("project_name") or None
        wait_reply = bool(payload.get("wait_reply", True))

        if not channel_id:
            return {"success": False, "error": "chat_id（Discord channel_id）必填"}

        text = _format_message(message, short_id, project_name, wait_reply)
        # Use last sent message in channel as reference for threading
        ref_id = self._last_sent.get(channel_id)
        msg_id = await self._send_raw(channel_id, text, ref_id)
        if msg_id is None:
            return {"success": False, "error": "发送失败"}
        self._last_sent[channel_id] = msg_id
        return {"success": True, "chat_id": channel_id}

    def status(self) -> dict:
        return {
            "worker_type": self.WORKER_TYPE,
            "bot_key": self.bot_key,
            "running": self._running,
            "connected": self._connected,
            "has_token": bool(self._token),
            "bot_id": self._bot_id,
            "session_id": self._session_id,
        }
