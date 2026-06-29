"""企业微信 AI Bot 内置引擎。

把企微 AI Bot 的 WebSocket 长连接收敛进 HIL Server 进程内。
协议参考：https://developer.work.weixin.qq.com/document/path/101463

- 连接 wss://openws.work.weixin.qq.com
- aibot_subscribe 鉴权（body 包裹 bot_id/secret，headers.req_id 必填）
- ping 心跳（每 30s）
- aibot_msg_callback 收用户消息 → 转 fly-pigeon 兼容结构 → storage.handle_callback
- aibot_send_msg 发消息（markdown）
- 断线自动重连；disconnected_event 仅记录（同凭证多连接互踢的信号）
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import threading
import time
from typing import Optional

import websockets

from .base import BaseEngine

logger = logging.getLogger(__name__)

# 引用回复：企微 AI Bot 将被引用内容以「...」\n 嵌入正文开头
_QUOTE_RE = re.compile(r'^「(.+?)」\s*', re.S)


# ── 凭证持久化 ──────────────────────────────────────────────────────────────

class WecomAibotStore:
    """企微 AI Bot 凭证持久化（JSON 文件，线程安全）。

    仿 iLink TokenStore：把 bot_id / bot_secret / bot_key 落盘，使 HIL Server
    重启后无需在管理台重新填写即可自动注册并启动 wecom-aibot 引擎。
    """

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
        else:
            self._data = {}

    def _save(self) -> None:
        d = os.path.dirname(self.path)
        if d and not os.path.exists(d):
            os.makedirs(d, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def get_credentials(self) -> Optional[dict]:
        with self._lock:
            bot_id = self._data.get("bot_id")
            bot_secret = self._data.get("bot_secret")
            if not bot_id or not bot_secret:
                return None
            return {
                "bot_id": bot_id,
                "bot_secret": bot_secret,
                "bot_key": self._data.get("bot_key") or "wecom-aibot-1",
            }

    def set_credentials(self, bot_id: str, bot_secret: str, bot_key: str) -> None:
        with self._lock:
            self._data["bot_id"] = bot_id
            self._data["bot_secret"] = bot_secret
            self._data["bot_key"] = bot_key
            self._save()

    def clear(self) -> None:
        with self._lock:
            self._data = {}
            self._save()


def _gen_req_id() -> str:
    return f"req_{int(time.time() * 1000)}_{random.randint(0, 0xFFFFFF):x}"


def _format_message_with_header(
    message: str, short_id: str, project_name: Optional[str], wait_reply: bool
) -> str:
    """企微 AI Bot 支持 markdown。与 devcloud-worker/hil 一致的头 + 引导回复。"""
    parts: list[str] = []
    if short_id:
        parts.append(f"[#{short_id} {project_name}]" if project_name else f"[#{short_id}]")
    parts.append(message)
    body = "\n".join(parts)
    if wait_reply:
        body = f"{body}\n\n> 请引用回复此消息"
    return body


class WecomAibotEngine(BaseEngine):
    """企微 AI Bot 内置引擎。"""

    def __init__(
        self,
        bot_key: str,
        bot_id: str,
        bot_secret: str,
        ws_url: str = "wss://openws.work.weixin.qq.com",
        heartbeat_interval: int = 30,
        reconnect_delay: int = 5,
    ):
        super().__init__(worker_type="wecom-aibot", bot_key=bot_key)
        self.bot_id = bot_id
        self.bot_secret = bot_secret
        self.ws_url = ws_url
        self.heartbeat_interval = heartbeat_interval
        self.reconnect_delay = reconnect_delay

        self._stopped = False
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._pending: dict[str, asyncio.Future] = {}
        self._ready = asyncio.Event()
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._send_lock = asyncio.Lock()

        # 已知收件人：收消息时记录，发消息时若未指定 chat_id 则取最近活跃的一个。
        # key = recipient（单聊=对方 userid，群聊=群 chatid）
        self._recipients: dict[str, dict] = {}

    # ── 生命周期 ───────────────────────────────────────────────────────────
    async def start(self) -> None:
        if not self.bot_id or not self.bot_secret:
            raise ValueError("wecom-aibot 引擎需要 bot_id 和 bot_secret")
        self._stopped = False
        asyncio.create_task(self._run_loop())
        logger.info(f"[wecom-aibot-engine] 启动: {self.ws_url}, bot_id={self.bot_id}")

    async def stop(self) -> None:
        self._stopped = True
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass

    async def _run_loop(self) -> None:
        delay = self.reconnect_delay
        while not self._stopped:
            try:
                await self._connect_and_serve()
                delay = self.reconnect_delay
            except Exception as e:
                logger.error(f"[wecom-aibot-engine] 连接异常: {e}，{delay}s 后重连")
            if self._stopped:
                break
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)

    async def _connect_and_serve(self) -> None:
        self._ready.clear()
        self._pending.clear()
        ws = await websockets.connect(
            self.ws_url, ping_interval=None, ping_timeout=None, close_timeout=10,
        )
        self._ws = ws
        logger.info(f"[wecom-aibot-engine] WS 已连接: {self.ws_url}")

        # 先把收消息循环跑成后台任务：订阅响应（以及后续心跳 ack/消息回调）
        # 都靠它读帧后经 _handle_message 解析；若等响应才开读循环，会因读不到
        # 响应而死锁超时。
        reader_task = asyncio.create_task(self._reader_loop(ws))

        # 订阅
        sub_id = _gen_req_id()
        sub_fut = asyncio.get_event_loop().create_future()
        self._pending[sub_id] = sub_fut
        await ws.send(json.dumps({
            "cmd": "aibot_subscribe",
            "headers": {"req_id": sub_id},
            "body": {"bot_id": self.bot_id, "secret": self.bot_secret},
        }))
        try:
            resp = await asyncio.wait_for(sub_fut, 30)
        except asyncio.TimeoutError:
            await self._abort_connection(ws, reader_task)
            raise RuntimeError("aibot_subscribe 超时")
        if resp.get("errcode") != 0:
            await self._abort_connection(ws, reader_task)
            raise RuntimeError(f"aibot_subscribe 失败: errcode={resp.get('errcode')}, errmsg={resp.get('errmsg')}")

        self._ready.set()
        logger.info("[wecom-aibot-engine] 订阅成功，连接就绪")

        # 心跳
        self._heartbeat_task = asyncio.create_task(self._heartbeat(ws))

        # 等待读循环结束（连接关闭时返回），结束后清理
        try:
            await reader_task
        except websockets.ConnectionClosed:
            pass
        except asyncio.CancelledError:
            raise
        finally:
            if self._heartbeat_task:
                self._heartbeat_task.cancel()
            self._ready.clear()
            self._pending.clear()
            if self._ws is ws:
                self._ws = None
            if not self._stopped:
                logger.warning("[wecom-aibot-engine] 连接断开，将重连")

    async def _reader_loop(self, ws) -> None:
        """后台读帧循环：把每帧交给 _handle_message 解析（含订阅响应、心跳 ack、消息回调）。"""
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                self._handle_message(msg)
        except websockets.ConnectionClosed:
            pass
        except asyncio.CancelledError:
            raise

    async def _abort_connection(self, ws, reader_task: asyncio.Task) -> None:
        """订阅失败/超时时收尾：取消读循环并关闭底层 ws，避免连接泄漏。"""
        reader_task.cancel()
        try:
            await reader_task
        except (asyncio.CancelledError, Exception):
            pass
        try:
            await ws.close()
        except Exception:
            pass
        if self._ws is ws:
            self._ws = None

    async def _heartbeat(self, ws) -> None:
        try:
            while not self._stopped:
                await asyncio.sleep(self.heartbeat_interval)
                if self._ws is not ws:
                    return
                ping_id = _gen_req_id()
                await self._send_raw(ws, {"cmd": "ping", "headers": {"req_id": ping_id}}, ping_id)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning(f"[wecom-aibot-engine] 心跳异常: {e}")

    # ── 收发 ───────────────────────────────────────────────────────────────
    async def _send_raw(self, ws, payload: dict, req_id: str) -> asyncio.Future:
        fut = asyncio.get_event_loop().create_future()
        self._pending[req_id] = fut
        await ws.send(json.dumps(payload))
        return fut

    def _handle_message(self, msg: dict) -> None:
        cmd = msg.get("cmd")
        req_id = (msg.get("headers") or {}).get("req_id")

        # 响应消息：无 cmd，按 req_id 匹配
        if not cmd and req_id and req_id in self._pending:
            fut = self._pending.pop(req_id)
            if not fut.done():
                fut.set_result(msg)
            return

        if cmd == "aibot_msg_callback":
            asyncio.create_task(self._on_msg_callback(msg))
            return

        if cmd == "aibot_event_callback":
            event_type = (msg.get("body") or {}).get("event", {}).get("eventtype")
            if event_type == "disconnected_event":
                logger.warning("[wecom-aibot-engine] 收到 disconnected_event，连接可能被新连接踢出")
            return

    async def _on_msg_callback(self, msg: dict) -> None:
        body = msg.get("body") or {}
        chat_type: str = body.get("chattype", "single")
        # 单聊无 chatid，用 from.userid 作为 recipient；群聊用 chatid
        if chat_type == "group":
            recipient = body.get("chatid", "")
        else:
            recipient = (body.get("from") or {}).get("userid", "")

        msg_type: str = body.get("msgtype", "")
        content: str = (body.get("text") or {}).get("content", "")
        if msg_type != "text":
            return
        if not recipient:
            return

        # 引用回复：提取「...」块作为 quote，剩余部分作为回复正文
        m = _QUOTE_RE.match(content)
        callback_data = {
            "chatid": recipient,
            "chattype": chat_type,
            "msgtype": "text",
            "from": body.get("from") or {},
        }
        if m:
            callback_data["quote"] = {"msgtype": "text", "text": {"content": m.group(1)}}
            callback_data["text"] = {"content": content[m.end():]}
        else:
            callback_data["text"] = {"content": content}

        logger.info(f"[wecom-aibot-engine] 收到消息: recipient={recipient}, text={content[:80]!r}")
        # 记录已知收件人（供 send_message 在未指定 chat_id 时解析）
        self._recipients[recipient] = {
            "recipient": recipient,
            "chat_type": chat_type,
            "from_user": body.get("from") or {},
            "last_active": time.time(),
        }
        if self.on_user_message:
            try:
                await self.on_user_message(callback_data)
            except Exception as e:
                logger.error(f"[wecom-aibot-engine] 处理用户消息失败: {e}", exc_info=True)

    async def send_message(self, payload: dict) -> dict:
        chat_id = payload.get("chat_id", "") or ""
        message = payload.get("message", "") or ""
        short_id = payload.get("short_id", "") or ""
        project_name = payload.get("project_name") or None
        wait_reply = bool(payload.get("wait_reply", True))

        if not chat_id:
            chat_id = self.resolve_recipient() or ""
        if not chat_id:
            return {
                "success": False,
                "error": "尚无已知收件人。请先在企业微信里给 bot 发一条消息激活，或在请求中指定 chat_id。",
            }

        try:
            await asyncio.wait_for(self._ready.wait(), 30)
        except asyncio.TimeoutError:
            return {"success": False, "error": "wecom-aibot 连接未就绪（订阅超时）"}

        if not self._ws:
            return {"success": False, "error": "wecom-aibot WebSocket 未连接"}

        formatted = _format_message_with_header(message, short_id, project_name, wait_reply)
        req_id = _gen_req_id()
        async with self._send_lock:
            try:
                fut = await self._send_raw(self._ws, {
                    "cmd": "aibot_send_msg",
                    "headers": {"req_id": req_id},
                    "body": {
                        "chatid": chat_id,
                        "chat_type": 0,
                        "msgtype": "markdown",
                        "markdown": {"content": formatted},
                    },
                }, req_id)
                resp = await asyncio.wait_for(fut, 15)
            except asyncio.TimeoutError:
                return {"success": False, "error": "发送响应超时"}
            except Exception as e:
                return {"success": False, "error": str(e)}

        if resp.get("errcode") != 0:
            return {"success": False, "error": f"errcode={resp.get('errcode')}, errmsg={resp.get('errmsg')}"}
        return {"success": True, "chat_id": chat_id}

    def status(self) -> dict:
        return {
            "worker_type": self.worker_type,
            "bot_key": self.bot_key,
            "bot_id": self.bot_id,
            "running": not self._stopped,
            "connected": self._ready.is_set(),
            "known_recipients": self.list_recipients(),
        }

    def resolve_recipient(self) -> Optional[str]:
        """取最近活跃的已知收件人（未指定 chat_id 时用）。"""
        if not self._recipients:
            return None
        latest = max(self._recipients.values(), key=lambda r: r.get("last_active", 0))
        return latest.get("recipient")

    def list_recipients(self) -> list[dict]:
        """按最近活跃倒序返回已知收件人（供管理台展示）。"""
        items = sorted(
            self._recipients.values(),
            key=lambda r: r.get("last_active", 0),
            reverse=True,
        )
        return [
            {
                "recipient": r["recipient"],
                "chat_type": r.get("chat_type", ""),
                "from_user": (r.get("from_user") or {}).get("name", ""),
                "last_active": r.get("last_active", 0),
            }
            for r in items
        ]
