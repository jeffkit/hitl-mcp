"""iLink 上游客户端：长轮询收消息、发送消息、扫码登录。

直接对接 https://ilinkai.weixin.qq.com （或自配置 base_url）。
本模块只做"和 iLink 服务端说话"，不涉及 HIL Server / WebSocket。
"""
from __future__ import annotations

import asyncio
import base64
import logging
import random
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import httpx

from .token_store import TokenStore

logger = logging.getLogger(__name__)

UA = "Mozilla/5.0 (compatible; iLink-Bot/1.0)"


def _random_uin() -> str:
    """iLink 要求 X-WECHAT-UIN 是 base64 编码的随机数。"""
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
        "client_id": f"worker-{random.randint(0, 0xFFFFFFFF):x}",
        "item_list": [{"type": 1, "text_item": {"text": text}}],
    }


@dataclass
class UserMessage:
    """从 iLink 长轮询解析出的一条用户消息。"""
    from_user_id: str
    context_token: str
    text: str
    raw: dict


class ILinkClient:
    """iLink 上游客户端。长轮询在 start() 内常驻，收到消息后回调 on_message。"""

    def __init__(self, base_url: str, token_store: TokenStore, poll_timeout: int = 40):
        self.base_url = base_url.rstrip("/")
        self.store = token_store
        self.poll_timeout = poll_timeout

        self._polling = False
        self._http = httpx.AsyncClient(timeout=httpx.Timeout((poll_timeout + 15, 30, 30)))

        # 扫码登录状态机
        self._pending_qr: dict | None = None  # {qrcode_key, qr_url, qr_base64, future}
        self._login_lock = asyncio.Lock()

        # 收到用户消息时触发（由 worker 注册）
        self.on_message: Callable[[UserMessage], Awaitable[None]] | None = None
        # 登录状态变化时触发（由 worker 注册，用于通知 HIL Server 工具列表）
        self.on_login_state_change: Callable[[], Awaitable[None]] | None = None

    # ── 生命周期 ───────────────────────────────────────────────
    async def start(self) -> None:
        if not self.store.get_bot_token():
            logger.warning("[iLink] 未找到 bot_token，等待 get_qr 触发扫码登录")
        self._polling = True
        asyncio.create_task(self._poll_loop())
        logger.info("[iLink] 长轮询已启动")

    async def stop(self) -> None:
        self._polling = False
        await self._http.aclose()

    # ── 长轮询 ─────────────────────────────────────────────────
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
                        "base_info": {"channel_version": "0.3.0", "bot_agent": "ilink-worker/0.1.0"},
                    },
                    timeout=self.poll_timeout + 15,
                )
                if res.status_code == 401:
                    logger.error("[iLink] bot_token 已失效，请重新扫码登录")
                    await asyncio.sleep(30)
                    continue
                if res.status_code != 200:
                    raise RuntimeError(f"HTTP {res.status_code}: {res.text[:200]}")

                data = res.json()
                logger.info(f"[iLink] getupdates 响应: keys={list(data.keys())}, msgs={len(data.get('msgs',[]) or [])}, buf_len={len(data.get('get_updates_buf','') or '')}")
                if data.get("get_updates_buf"):
                    self.store.set_updates_buf(data["get_updates_buf"])

                for msg in data.get("msgs", []) or []:
                    await self._process_update(msg)

                retry_delay = 3.0
            except Exception as e:
                logger.error(f"[iLink] 轮询异常: {e}，{retry_delay}s 后重试")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 60)

    async def _process_update(self, msg: dict) -> None:
        from_user_id = msg.get("from_user_id", "") or ""
        context_token = msg.get("context_token", "") or ""
        text = _extract_text(msg)
        logger.info(f"[iLink] 收到消息: user={from_user_id}, text={text[:80]!r}")

        if context_token and from_user_id:
            self.store.set_context_token(from_user_id, context_token)

        if from_user_id and text and self.on_message:
            await self.on_message(UserMessage(from_user_id, context_token, text, msg))

    # ── 发送消息 ───────────────────────────────────────────────
    async def send_message(self, to_user_id: str, text: str) -> tuple[bool, str | None]:
        """返回 (success, error)。"""
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
                    "base_info": {"channel_version": "0.3.0", "bot_agent": "ilink-worker/0.1.0"},
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

    # ── 扫码登录（供 HIL Server 通过 WS 触发） ────────────────
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
        """获取二维码。若已有 pending QR 则复用，否则申请新 QR 并启动后台轮询。

        返回: { status, qr_url, qr_base64, qrcode_key }
        """
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
                    # 服务端未直接返回图片，用 qrcode 库生成（若可用）
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
                if self.on_login_state_change:
                    asyncio.create_task(self.on_login_state_change())
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
                        logger.info("[iLink] 扫码登录成功")
                    fut = self._pending_qr["future"]
                    self._pending_qr = None
                    if not fut.done():
                        fut.set_result("success")
                    if self.on_login_state_change:
                        asyncio.create_task(self.on_login_state_change())
                    return
                if status == "expired":
                    logger.warning("[iLink] 二维码已过期")
                    fut = self._pending_qr["future"]
                    self._pending_qr = None
                    if not fut.done():
                        fut.set_result("expired")
                    if self.on_login_state_change:
                        asyncio.create_task(self.on_login_state_change())
                    return
            except Exception:
                continue

    async def wait_login(self) -> str:
        """阻塞等待当前 pending QR 的结果，返回 'success' / 'expired' / 'not_started'。"""
        if self.is_logged_in:
            return "success"
        if not self._pending_qr:
            return "not_started"
        return await self._pending_qr["future"]
