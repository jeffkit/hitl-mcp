"""飞书（Lark）内置引擎。

通过飞书 WebSocket 长连接（企业自建应用）接收消息，REST API 发消息：
- 订阅 im.message.receive_v1 事件
- 收到消息 → 转 fly-pigeon 兼容结构 → storage.handle_callback
- 发送时带 [#short_id] 头，支持 reply_in_thread

依赖：lark-oapi>=1.0.0（pip install lark-oapi）
管理台：POST /admin/api/engines/feishu/start  { app_id, app_secret, bot_key }

Short-ID 匹配：
- 如果消息为线程回复（parent_id），尝试从 quote 中提取 [#short_id]
- 当前消息文本中直接含 [#short_id]
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
FEISHU_API = "https://open.feishu.cn/open-apis"


# ── 凭证持久化 ─────────────────────────────────────────────────────────────────

class FeishuStore:
    """飞书凭证持久化（JSON 文件，线程安全）。"""

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

    def get_credentials(self) -> Optional[dict]:
        with self._lock:
            app_id = self._data.get("app_id")
            app_secret = self._data.get("app_secret")
            if not app_id or not app_secret:
                return None
            return {"app_id": app_id, "app_secret": app_secret,
                    "bot_key": self._data.get("bot_key") or "feishu-1"}

    def set_credentials(self, app_id: str, app_secret: str, bot_key: str) -> None:
        with self._lock:
            self._data["app_id"] = app_id
            self._data["app_secret"] = app_secret
            self._data["bot_key"] = bot_key
            self._save()

    def clear(self) -> None:
        with self._lock:
            self._data = {}
            self._save()


# ── Token 管理 ─────────────────────────────────────────────────────────────────

class _AppTokenCache:
    """自动刷新 app_access_token（有效期通常 2 小时）。"""

    def __init__(self, app_id: str, app_secret: str):
        self._app_id = app_id
        self._app_secret = app_secret
        self._token: Optional[str] = None
        self._expire_at: float = 0.0
        self._lock = asyncio.Lock()

    async def get(self, http: httpx.AsyncClient) -> str:
        import time
        async with self._lock:
            if self._token and time.time() < self._expire_at - 300:
                return self._token
            resp = await http.post(
                f"{FEISHU_API}/auth/v3/app_access_token/internal",
                json={"app_id": self._app_id, "app_secret": self._app_secret},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(f"获取 app_access_token 失败: {data}")
            self._token = data["app_access_token"]
            self._expire_at = time.time() + data.get("expire", 7200)
            return self._token


# ── 辅助函数 ───────────────────────────────────────────────────────────────────

def _extract_short_id(text: str) -> Optional[str]:
    m = _SHORT_ID_RE.search(text or "")
    return m.group(1) if m else None


def _parse_message_content(message: dict) -> str:
    """从飞书消息对象提取纯文本。"""
    msg_type = message.get("msg_type") or ""
    body = message.get("body") or {}
    content_raw = body.get("content") or ""
    try:
        content_data = json.loads(content_raw)
    except Exception:
        return content_raw

    if msg_type == "text":
        return content_data.get("text") or ""
    if msg_type == "post":
        # 富文本：提取所有 text 节点
        parts: list[str] = []
        for lang_content in content_data.values():
            for paragraph in lang_content.get("content") or []:
                for elem in paragraph:
                    if elem.get("tag") == "text":
                        parts.append(elem.get("text") or "")
        return " ".join(parts)
    return content_raw


def _to_callback_data(event: dict, sender: dict) -> Optional[dict]:
    """飞书 im.message.receive_v1 → fly-pigeon callback_data。"""
    message = event.get("message") or {}
    text = _parse_message_content(message)
    if not text.strip():
        return None

    open_id = (sender.get("sender_id") or {}).get("open_id") or ""
    chat_id = str(message.get("chat_id") or open_id)
    chat_type = message.get("chat_type") or "p2p"

    data: dict = {
        "chatid": open_id or chat_id,
        "chattype": "single" if chat_type == "p2p" else "group",
        "msgtype": "text",
        "text": {"content": text},
        "from": {"userid": open_id, "name": ""},
        "raw_feishu_event": event,
    }

    # Short-ID from current message
    sid = _extract_short_id(text)
    if sid:
        data["short_id"] = sid

    # parent_id: this is a thread reply — check mentions for short_id
    parent_id = message.get("parent_id")
    if parent_id:
        data["ref_msg_id"] = parent_id  # used as hint by storage

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

class FeishuEngine(BaseEngine):
    """飞书内置引擎（lark-oapi WebSocket 长连接）。"""

    WORKER_TYPE = "feishu"

    def __init__(self, bot_key: str, app_id: str, app_secret: str, store: FeishuStore):
        super().__init__(worker_type=self.WORKER_TYPE, bot_key=bot_key)
        self._app_id = app_id
        self._app_secret = app_secret
        self._store = store
        self._running = False
        self._connected = False
        self._http: Optional[httpx.AsyncClient] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws_thread: Optional[threading.Thread] = None
        self._token_cache = _AppTokenCache(app_id, app_secret)

    async def start(self) -> None:
        try:
            import lark_oapi as lark  # type: ignore
        except ImportError:
            raise RuntimeError(
                "飞书引擎需要 lark-oapi 依赖。请运行: pip install lark-oapi"
            )

        self._http = httpx.AsyncClient(timeout=15)
        self._loop = asyncio.get_event_loop()
        self._running = True
        self._ws_thread = threading.Thread(target=self._run_lark, daemon=True, name="feishu-ws")
        self._ws_thread.start()
        logger.info(f"[feishu-engine] 已启动 (bot_key={self.bot_key}, app_id={self._app_id})")

    def _run_lark(self) -> None:
        """在独立线程中运行 lark_oapi WebSocket 客户端（阻塞调用）。"""
        import lark_oapi as lark  # type: ignore

        def _handler(data) -> None:
            """飞书 im.message.receive_v1 事件处理（同步，在 lark SDK 线程中调用）。"""
            try:
                event = {}
                sender = {}
                # lark_oapi v1 事件对象有 .event 属性
                if hasattr(data, "event"):
                    ev = data.event
                    message = getattr(ev, "message", None) or {}
                    sender_obj = getattr(ev, "sender", None)
                    if message:
                        # Convert lark SDK object to dict
                        event["message"] = self._lark_obj_to_dict(message)
                    if sender_obj:
                        sender = self._lark_obj_to_dict(sender_obj)
                else:
                    event = getattr(data, "dict", lambda: {})() or {}
                    sender = {}

                cb = _to_callback_data(event, sender)
                if cb and self.on_user_message and self._loop:
                    asyncio.run_coroutine_threadsafe(
                        self._dispatch(cb), self._loop
                    )
            except Exception as e:
                logger.error(f"[feishu-engine] 消息处理异常: {e}", exc_info=True)

        try:
            handler = (
                lark.EventDispatcherHandler.builder("", "")
                .register_p2_im_message_receive_v1(_handler)
                .build()
            )
            client = lark.ws.Client(
                self._app_id, self._app_secret,
                event_handler=handler,
                log_level=lark.LogLevel.ERROR,
            )
            self._connected = True
            client.start()  # blocking
        except Exception as e:
            logger.error(f"[feishu-engine] WebSocket 客户端异常: {e}", exc_info=True)
        finally:
            self._connected = False

    def _lark_obj_to_dict(self, obj) -> dict:
        """将 lark_oapi SDK 对象递归转成 dict（兼容 v1/v2 SDK）。"""
        if isinstance(obj, dict):
            return obj
        try:
            import dataclasses
            if dataclasses.is_dataclass(obj):
                return dataclasses.asdict(obj)
        except Exception:
            pass
        # Fallback: use __dict__ or to_dict()
        if hasattr(obj, "to_dict"):
            return obj.to_dict()
        if hasattr(obj, "__dict__"):
            result = {}
            for k, v in obj.__dict__.items():
                if not k.startswith("_"):
                    result[k] = self._lark_obj_to_dict(v) if hasattr(v, "__dict__") else v
            return result
        return {}

    async def _dispatch(self, cb: dict) -> None:
        """在 asyncio 线程中实际处理回调（由 _handler 通过 run_coroutine_threadsafe 调用）。"""
        logger.info(
            f"[feishu-engine] 收到消息: user={cb['from']['userid']}, "
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
                    await self._send_text(cb["chatid"], prompt)
            except Exception as e:
                logger.error(f"[feishu-engine] 回调处理失败: {e}", exc_info=True)

    async def stop(self) -> None:
        self._running = False
        self._connected = False
        if self._http:
            await self._http.aclose()
            self._http = None
        # 飞书 SDK 无优雅停止方法；守护线程会在进程退出时自动终止
        logger.info(f"[feishu-engine] 已停止 (bot_key={self.bot_key})")

    async def _send_text(self, open_id: str, text: str,
                          reply_to_msg_id: Optional[str] = None) -> Optional[str]:
        """发送文本消息（open_id 模式）。"""
        try:
            token = await self._token_cache.get(self._http)
            payload: dict = {
                "receive_id": open_id,
                "msg_type": "text",
                "content": json.dumps({"text": text}),
            }
            if reply_to_msg_id:
                payload["reply_in_thread"] = False
                payload["quote_message_id"] = reply_to_msg_id
            resp = await self._http.post(
                f"{FEISHU_API}/im/v1/messages",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
                params={"receive_id_type": "open_id"},
                json=payload,
                timeout=15,
            )
            if not resp.is_success:
                logger.warning(f"[feishu-engine] 发送失败: {resp.status_code} {resp.text[:200]}")
                return None
            data = resp.json()
            if data.get("code") != 0:
                logger.warning(f"[feishu-engine] 发送返回错误: {data}")
                return None
            return str((data.get("data") or {}).get("message_id") or "")
        except Exception as e:
            logger.error(f"[feishu-engine] 发送异常: {e}")
            return None

    async def send_message(self, payload: dict) -> dict:
        chat_id = str(payload.get("chat_id") or "")
        message = payload.get("message") or ""
        short_id = payload.get("short_id") or ""
        project_name = payload.get("project_name") or None
        wait_reply = bool(payload.get("wait_reply", True))

        if not chat_id:
            return {"success": False, "error": "chat_id（飞书 open_id）必填"}

        text = _format_message(message, short_id, project_name, wait_reply)
        msg_id = await self._send_text(chat_id, text)
        if msg_id is None:
            return {"success": False, "error": "发送失败"}
        return {"success": True, "chat_id": chat_id}

    def status(self) -> dict:
        return {
            "worker_type": self.WORKER_TYPE,
            "bot_key": self.bot_key,
            "running": self._running,
            "connected": self._connected,
            "app_id": self._app_id,
        }
