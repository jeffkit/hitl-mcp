"""iLink 内置引擎。

把原本 ilink-worker 独立进程维持的 iLink 长轮询、扫码登录、发消息逻辑
收敛进 HIL Server 进程内。收到用户消息后转成 fly-pigeon 兼容结构，
通过 on_user_message 回调直接交给 storage.handle_callback。

凭证（bot_token / get_updates_buf / context_tokens）持久化在本地 JSON 文件，
与 ilink-worker 共用同一文件格式，可无缝迁移。
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import random
import threading
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

import httpx

from .base import BaseEngine

logger = logging.getLogger(__name__)

UA = "Mozilla/5.0 (compatible; iLink-Bot/1.0)"


# ── Token 持久化 ──────────────────────────────────────────────────────────

class TokenStore:
    """iLink 凭证持久化（JSON 文件，线程安全）。"""

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

    def get_bot_token(self) -> Optional[str]:
        with self._lock:
            return self._data.get("bot_token")

    def set_bot_token(self, token: str) -> None:
        with self._lock:
            self._data["bot_token"] = token
            self._save()

    def get_updates_buf(self) -> str:
        with self._lock:
            return self._data.get("get_updates_buf", "")

    def set_updates_buf(self, buf: str) -> None:
        with self._lock:
            self._data["get_updates_buf"] = buf
            self._save()

    def get_context_token(self, from_user_id: str) -> Optional[str]:
        with self._lock:
            return (self._data.get("context_tokens") or {}).get(from_user_id)

    def set_context_token(self, from_user_id: str, token: str) -> None:
        with self._lock:
            self._data.setdefault("context_tokens", {})[from_user_id] = token
            self._save()

    def list_known_users(self) -> list[dict]:
        with self._lock:
            return [
                {"from_user_id": uid, "has_context_token": bool(t)}
                for uid, t in (self._data.get("context_tokens") or {}).items()
            ]

    def resolve_recipient(self) -> Optional[str]:
        with self._lock:
            users = list((self._data.get("context_tokens") or {}).keys())
            return users[0] if users else None


# ── iLink 上游客户端 ──────────────────────────────────────────────────────

def _random_uin() -> str:
    return base64.b64encode(str(random.randint(0, 0xFFFFFFFF)).encode()).decode()


def _ilink_headers(bot_token: str) -> dict[str, str]:
    return {
        "AuthorizationType": "ilink_bot_token",
        "Authorization": f"Bearer {bot_token}",
        "Content-Type": "application/json",
        "User-Agent": UA,
        "X-WECHAT-UIN": _random_uin(),
    }


def _extract_text(msg: dict) -> str:
    for item in msg.get("item_list", []) or []:
        text = (item.get("text_item") or {}).get("text") or (item.get("voice_item") or {}).get("text")
        if text:
            return text
    return ""


def _build_text_reply(context_token: str, text: str, to_user_id: str) -> dict:
    return {
        "context_token": context_token,
        "to_user_id": to_user_id,
        "from_user_id": "",
        "message_type": 2,
        "message_state": 2,
        "client_id": f"hil-{random.randint(0, 0xFFFFFFFF):x}",
        "item_list": [{"type": 1, "text_item": {"text": text}}],
    }


@dataclass
class UserMessage:
    from_user_id: str
    context_token: str
    text: str
    raw: dict


class ILinkClient:
    """iLink 上游客户端：长轮询收消息、发消息、扫码登录。"""

    def __init__(self, base_url: str, token_store: TokenStore, poll_timeout: int = 40):
        self.base_url = base_url.rstrip("/")
        self.store = token_store
        self.poll_timeout = poll_timeout

        self._polling = False
        self._http: Optional[httpx.AsyncClient] = None

        # 扫码登录状态机
        self._pending_qr: Optional[dict] = None  # {qrcode_key, qr_url, qr_base64, future}
        self._login_lock = asyncio.Lock()

        self.on_message: Optional[Callable[[UserMessage], Awaitable[None]]] = None

    async def start(self) -> None:
        if not self.store.get_bot_token():
            logger.warning("[ilink-engine] 未找到 bot_token，等待 get_qr 触发扫码登录")
        self._http = httpx.AsyncClient(timeout=httpx.Timeout((self.poll_timeout + 15, 30, 30)))
        self._polling = True
        asyncio.create_task(self._poll_loop())
        logger.info(f"[ilink-engine] 长轮询已启动: {self.base_url}")

    async def stop(self) -> None:
        self._polling = False
        if self._http:
            await self._http.aclose()
            self._http = None

    async def _poll_loop(self) -> None:
        retry_delay = 3.0
        while self._polling:
            bot_token = self.store.get_bot_token()
            if not bot_token:
                await asyncio.sleep(5)
                continue
            try:
                buf = self.store.get_updates_buf()
                res = await self._http.post(
                    f"{self.base_url}/ilink/bot/getupdates",
                    headers=_ilink_headers(bot_token),
                    json={
                        "get_updates_buf": buf,
                        "timeout": self.poll_timeout,
                        "base_info": {"channel_version": "0.3.0", "bot_agent": "hil-server-ilink/0.1.0"},
                    },
                    timeout=self.poll_timeout + 15,
                )
                if res.status_code == 401:
                    logger.error("[ilink-engine] bot_token 已失效，请重新扫码登录")
                    await asyncio.sleep(30)
                    continue
                if res.status_code != 200:
                    raise RuntimeError(f"HTTP {res.status_code}: {res.text[:200]}")

                data = res.json()
                if data.get("get_updates_buf"):
                    self.store.set_updates_buf(data["get_updates_buf"])

                for msg in data.get("msgs", []) or []:
                    await self._process_update(msg)

                retry_delay = 3.0
            except Exception as e:
                logger.error(f"[ilink-engine] 轮询异常: {e}，{retry_delay}s 后重试")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 60)

    async def _process_update(self, msg: dict) -> None:
        from_user_id = msg.get("from_user_id", "") or ""
        context_token = msg.get("context_token", "") or ""
        text = _extract_text(msg)
        logger.info(f"[ilink-engine] 收到消息: user={from_user_id}, text={text[:80]!r}")

        if context_token and from_user_id:
            self.store.set_context_token(from_user_id, context_token)

        if from_user_id and text and self.on_message:
            await self.on_message(UserMessage(from_user_id, context_token, text, msg))

    async def send_message(self, to_user_id: str, text: str) -> tuple[bool, Optional[str]]:
        bot_token = self.store.get_bot_token()
        if not bot_token:
            return False, "未登录（无 bot_token）"
        context_token = self.store.get_context_token(to_user_id)
        if not context_token:
            return False, f"用户未激活: {to_user_id}"
        try:
            res = await self._http.post(
                f"{self.base_url}/ilink/bot/sendmessage",
                headers=_ilink_headers(bot_token),
                json={
                    "msg": _build_text_reply(context_token, text, to_user_id),
                    "base_info": {"channel_version": "0.3.0", "bot_agent": "hil-server-ilink/0.1.0"},
                },
                timeout=15,
            )
            if res.status_code != 200:
                return False, f"HTTP {res.status_code}"
            raw = res.text
            if not raw.strip():
                return True, None
            data = res.json()
            if data.get("ret") not in (None, 0):
                return False, f"ret={data.get('ret')}, errmsg={data.get('errmsg')}"
            return True, None
        except Exception as e:
            return False, str(e)

    # ── 扫码登录 ───────────────────────────────────────────────────────────
    @property
    def is_logged_in(self) -> bool:
        return bool(self.store.get_bot_token())

    @property
    def login_status(self) -> str:
        if self.is_logged_in:
            return "success"
        if self._pending_qr:
            return "pending"
        return "not_started"

    async def get_qr(self) -> dict:
        async with self._login_lock:
            if self._pending_qr:
                return {
                    "status": "pending",
                    "qr_url": self._pending_qr["qr_url"],
                    "qr_base64": self._pending_qr["qr_base64"],
                    "qrcode_key": self._pending_qr["qrcode_key"],
                }
            try:
                res = await self._http.get(
                    f"{self.base_url}/ilink/bot/get_bot_qrcode",
                    params={"bot_type": 3},
                    headers={"User-Agent": UA},
                    timeout=15,
                )
                if res.status_code != 200:
                    raise RuntimeError(f"get_bot_qrcode HTTP {res.status_code}")
                data = res.json()
                if data.get("ret") != 0:
                    raise RuntimeError(data.get("errmsg") or f"ret={data.get('ret')}")

                qrcode_key = data.get("qrcode", "")
                qr_url = data.get("qrcode_img_content", "")
                if not qrcode_key or not qr_url:
                    raise RuntimeError("无法获取二维码")

                qr_base64 = data.get("qrcode_base64") or ""
                if not qr_base64:
                    try:
                        import qrcode  # type: ignore
                        import io
                        buf = io.BytesIO()
                        qrcode.make(qr_url).save(buf, format="PNG")
                        qr_base64 = base64.b64encode(buf.getvalue()).decode()
                    except Exception:
                        qr_base64 = ""

                loop = asyncio.get_event_loop()
                future: asyncio.Future = loop.create_future()
                self._pending_qr = {
                    "qrcode_key": qrcode_key,
                    "qr_url": qr_url,
                    "qr_base64": qr_base64,
                    "future": future,
                }
                asyncio.create_task(self._poll_login(qrcode_key))
                return {
                    "status": "pending",
                    "qr_url": qr_url,
                    "qr_base64": qr_base64,
                    "qrcode_key": qrcode_key,
                }
            except Exception as e:
                return {"status": "error", "error": str(e)}

    async def _poll_login(self, qrcode_key: str) -> None:
        while self._pending_qr and self._pending_qr["qrcode_key"] == qrcode_key:
            await asyncio.sleep(2)
            if not self._pending_qr:
                return
            try:
                res = await self._http.get(
                    f"{self.base_url}/ilink/bot/get_qrcode_status",
                    params={"qrcode": qrcode_key},
                    headers={"User-Agent": UA},
                    timeout=35,
                )
                if res.status_code != 200:
                    continue
                data = res.json()
                status = data.get("status", "")
                if status == "confirmed":
                    bot_token = data.get("bot_token", "")
                    if bot_token:
                        self.store.set_bot_token(bot_token)
                        logger.info("[ilink-engine] 扫码登录成功")
                    fut = self._pending_qr["future"]
                    self._pending_qr = None
                    if not fut.done():
                        fut.set_result("success")
                    return
                if status == "expired":
                    logger.warning("[ilink-engine] 二维码已过期")
                    fut = self._pending_qr["future"]
                    self._pending_qr = None
                    if not fut.done():
                        fut.set_result("expired")
                    return
            except Exception:
                continue


# ── 消息头拼接（与 ilink-worker 一致）─────────────────────────────────────

def _format_message_with_header(
    message: str, short_id: str, project_name: Optional[str], wait_reply: bool
) -> str:
    """iLink 是纯文本通道（不支持 markdown），footer 用纯文本。

    尾部提示与 wecom-aibot 引擎保持一致文案「> 请引用回复此消息」，引导用户
    长按引用回复，以便 storage.parse_quoted_message 从引用块中提取 short_id
    完成精确会话匹配。
    """
    parts: list[str] = []
    if short_id:
        parts.append(f"[#{short_id} {project_name}]" if project_name else f"[#{short_id}]")
    parts.append(message)
    body = "\n".join(parts)
    if wait_reply:
        body = f"{body}\n\n> 请引用回复此消息"
    return body


def _to_callback_data(msg: UserMessage) -> dict:
    """转成 fly-pigeon 兼容结构，供 storage.handle_callback 消费。"""
    return {
        "chatid": msg.from_user_id,
        "chattype": "single",
        "msgtype": "text",
        "text": {"content": msg.text},
        "from": {"userid": msg.from_user_id, "name": ""},
    }


# ── 引擎 ──────────────────────────────────────────────────────────────────

class ILinkEngine(BaseEngine):
    """iLink 内置引擎。"""

    def __init__(self, bot_key: str, base_url: str, token_store_path: str, poll_timeout: int = 40):
        super().__init__(worker_type="ilink", bot_key=bot_key)
        self.store = TokenStore(token_store_path)
        self.client = ILinkClient(base_url, self.store, poll_timeout)
        self.client.on_message = self._on_user_message

    async def _on_user_message(self, msg: UserMessage) -> None:
        callback_data = _to_callback_data(msg)
        if self.on_user_message:
            try:
                await self.on_user_message(callback_data)
            except Exception as e:
                logger.error(f"[ilink-engine] 处理用户消息失败: {e}", exc_info=True)

    async def start(self) -> None:
        await self.client.start()

    async def stop(self) -> None:
        await self.client.stop()

    async def send_message(self, payload: dict) -> dict:
        chat_id = payload.get("chat_id", "") or ""
        message = payload.get("message", "") or ""
        short_id = payload.get("short_id", "") or ""
        project_name = payload.get("project_name") or None
        wait_reply = bool(payload.get("wait_reply", True))

        if not chat_id:
            chat_id = self.store.resolve_recipient() or ""
        if not chat_id:
            return {"success": False, "error": "尚无已激活用户，无法发送"}
        if not self.client.is_logged_in:
            return {"success": False, "error": "login_required"}

        formatted = _format_message_with_header(message, short_id, project_name, wait_reply)
        ok, err = await self.client.send_message(chat_id, formatted)
        return {"success": ok, "chat_id": chat_id if ok else None, "error": err}

    # ── ilink 专属：登录接口 ───────────────────────────────────────────────
    async def get_qr(self) -> dict:
        return await self.client.get_qr()

    async def get_login_status(self) -> dict:
        return {"status": self.client.login_status}

    async def list_activated_users(self) -> dict:
        return {"users": self.store.list_known_users()}

    def status(self) -> dict:
        return {
            "worker_type": self.worker_type,
            "bot_key": self.bot_key,
            "running": self.client._polling,
            "logged_in": self.client.is_logged_in,
            "login_status": self.client.login_status,
            "activated_users": self.store.list_known_users(),
        }
