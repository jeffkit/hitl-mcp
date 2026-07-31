"""Telegram Bot API 内置引擎。

使用 Bot API getUpdates 长轮询接收消息，sendMessage 发消息：
- 收到用户消息 → 转 fly-pigeon 兼容结构 → storage.handle_callback
- 发送时带 [#short_id] 头，支持 reply_to_message_id 追线程

凭证：bot_token 存入 ~/.hil-mcp/telegram_store.json
管理台：POST /admin/api/engines/telegram/start  { bot_token, bot_key }

Short-ID 匹配优先级：
1. reply_to_message.text 中提取 [#short_id]（引用回复精确匹配）
2. 当前消息文本中直接含 [#short_id]
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
from typing import Optional

import httpx

from .base import BaseEngine

logger = logging.getLogger(__name__)

_SHORT_ID_RE = re.compile(r'\[#([a-f0-9]{8,12})(?:\s+[^\]]+)?\]')
TG_API = "https://api.telegram.org"


# ── 凭证持久化 ─────────────────────────────────────────────────────────────────

class TelegramStore:
    """Telegram 凭证持久化（JSON 文件，线程安全）。"""

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


def _to_callback_data(update: dict) -> Optional[dict]:
    """Telegram Update → fly-pigeon 兼容 callback_data。"""
    msg = update.get("message") or update.get("channel_post")
    if not msg:
        return None
    text = msg.get("text") or ""
    if not text.strip():
        return None

    chat_id = str(msg["chat"]["id"])
    user = msg.get("from") or {}
    user_id = str(user.get("id") or chat_id)
    name = user.get("username") or user.get("first_name") or ""

    data: dict = {
        "chatid": chat_id,
        "chattype": "single" if msg["chat"]["type"] in ("private",) else "group",
        "msgtype": "text",
        "text": {"content": text},
        "from": {"userid": user_id, "name": name},
        "raw_tg_update": update,
    }

    # Short-ID：先从引用回复的被引用消息中提取（最强）
    reply_to = msg.get("reply_to_message")
    if reply_to:
        ref_text = reply_to.get("text") or ""
        sid = _extract_short_id(ref_text)
        if sid:
            data["short_id"] = sid
        if ref_text:
            data["quote"] = {"msgtype": "text", "text": {"content": ref_text}}

    # 次：当前消息文本中有 [#short_id]
    if "short_id" not in data:
        sid = _extract_short_id(text)
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
        body = f"{body}\n\n> 请回复此消息以便系统自动关联"
    return body


# ── 引擎 ───────────────────────────────────────────────────────────────────────

class TelegramEngine(BaseEngine):
    """Telegram Bot API 内置引擎。"""

    WORKER_TYPE = "telegram"

    def __init__(self, bot_key: str, bot_token: str, store: TelegramStore,
                 poll_timeout: int = 30):
        super().__init__(worker_type=self.WORKER_TYPE, bot_key=bot_key)
        self._token = bot_token
        self._store = store
        self._poll_timeout = poll_timeout
        self._running = False
        self._http: Optional[httpx.AsyncClient] = None
        self._offset = 0
        # map sent_message_id → reply_to_message_id (for threading)
        self._sent_msg_ids: dict[str, int] = {}  # chat_id → last sent message_id

    def _url(self, method: str) -> str:
        return f"{TG_API}/bot{self._token}/{method}"

    async def start(self) -> None:
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(self._poll_timeout + 10, connect=15)
        )
        self._running = True
        asyncio.create_task(self._poll_loop())
        logger.info(f"[telegram-engine] 长轮询已启动 (bot_key={self.bot_key})")

    async def stop(self) -> None:
        self._running = False
        if self._http:
            await self._http.aclose()
            self._http = None
        logger.info(f"[telegram-engine] 已停止 (bot_key={self.bot_key})")

    async def _poll_loop(self) -> None:
        retry_delay = 3.0
        while self._running:
            try:
                resp = await self._http.get(
                    self._url("getUpdates"),
                    params={"offset": self._offset, "timeout": self._poll_timeout, "limit": 100},
                    timeout=self._poll_timeout + 10,
                )
                if resp.status_code == 401:
                    logger.error("[telegram-engine] Bot token 无效，停止轮询")
                    self._running = False
                    return
                resp.raise_for_status()
                data = resp.json()
                for upd in data.get("result") or []:
                    self._offset = upd["update_id"] + 1
                    await self._handle_update(upd)
                retry_delay = 3.0
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"[telegram-engine] 轮询异常: {e}，{retry_delay}s 后重试")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 60)

    async def _handle_update(self, update: dict) -> None:
        cb = _to_callback_data(update)
        if not cb:
            return
        logger.info(
            f"[telegram-engine] 收到消息: chat={cb['chatid']}, "
            f"text={cb['text']['content'][:60]!r}"
        )
        if self.on_user_message:
            try:
                result = await self.on_user_message(cb)
                if isinstance(result, dict) and result.get("prompt_user"):
                    waiting_ids = result.get("waiting_short_ids", [])
                    prompt = (
                        f"⚠️ 有 {len(waiting_ids)} 条待回复，请回复对应消息以匹配：\n"
                        + "\n".join(f"  [#{sid}]" for sid in waiting_ids)
                    )
                    await self._send_raw(cb["chatid"], prompt)
            except Exception as e:
                logger.error(f"[telegram-engine] 处理消息失败: {e}", exc_info=True)

    async def _send_raw(self, chat_id: str, text: str,
                        reply_to_message_id: Optional[int] = None) -> Optional[int]:
        """发送消息，返回 message_id（失败返回 None）。"""
        params: dict = {"chat_id": chat_id, "text": text}
        if reply_to_message_id:
            params["reply_to_message_id"] = reply_to_message_id
        try:
            resp = await self._http.post(self._url("sendMessage"), json=params, timeout=15)
            if not resp.is_success:
                logger.warning(f"[telegram-engine] sendMessage 失败: {resp.status_code} {resp.text[:200]}")
                return None
            data = resp.json()
            if not data.get("ok"):
                logger.warning(f"[telegram-engine] sendMessage 返回错误: {data}")
                return None
            msg_id: int = data["result"]["message_id"]
            return msg_id
        except Exception as e:
            logger.error(f"[telegram-engine] 发送异常: {e}")
            return None

    async def send_message(self, payload: dict) -> dict:
        chat_id = str(payload.get("chat_id") or "")
        message = payload.get("message") or ""
        short_id = payload.get("short_id") or ""
        project_name = payload.get("project_name") or None
        wait_reply = bool(payload.get("wait_reply", True))

        if not chat_id:
            return {"success": False, "error": "chat_id 必填（Telegram 需要 chat_id）"}

        text = _format_message(message, short_id, project_name, wait_reply)
        # Reply to last sent message in this chat to create a thread
        reply_to = self._sent_msg_ids.get(chat_id)
        msg_id = await self._send_raw(chat_id, text, reply_to)
        if msg_id is None:
            return {"success": False, "error": "发送失败"}
        self._sent_msg_ids[chat_id] = msg_id
        return {"success": True, "chat_id": chat_id}

    def status(self) -> dict:
        return {
            "worker_type": self.WORKER_TYPE,
            "bot_key": self.bot_key,
            "running": self._running,
            "has_token": bool(self._token),
        }
