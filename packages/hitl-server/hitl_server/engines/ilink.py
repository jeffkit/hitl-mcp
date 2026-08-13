"""iLink 内置引擎。

在 HITL Server 进程内维持 iLink 长轮询、扫码登录、发消息逻辑。
收到用户消息后转成 fly-pigeon 兼容结构，通过 on_user_message 回调
直接交给 storage.handle_callback。

凭证（bot_token / get_updates_buf / context_tokens）持久化在本地 JSON 文件。
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import random
import re
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Optional

import httpx

from .base import BaseEngine

logger = logging.getLogger(__name__)

UA = "Mozilla/5.0 (compatible; iLink-Bot/1.0)"

# iLink CDN 域名（媒体文件加密上传）
_ILINK_CDN_BASE = "https://novac2c.cdn.weixin.qq.com/c2c"

# iLink 媒体/消息类型常量（与 openclaw-weixin types.ts 对齐）
_MEDIA_TYPE_IMAGE = 1
_ITEM_TYPE_IMAGE = 2

# 与 storage.SESSION_ID_PATTERN 保持一致：匹配 [#short_id] 或 [#short_id 项目名]
# 兼容 8~12 位 hex（历史 8 位 / 新 12 位）
_ILINK_SESSION_ID_RE = re.compile(r'\[#([a-f0-9]{8,12})(?:\s+[^\]]+)?\]')


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


def _extract_ref_msg_id(msg: dict) -> str:
    """从 iLink 消息中提取引用回复所指向的原始消息 ID。

    iLink 引用回复时，原始消息内容不会随回调下发，只有被引用消息的 msg_id：
        item_list[].ref_msg.message_item.msg_id

    返回字符串格式的 msg_id；非引用消息或字段缺失时返回空字符串。
    """
    for item in msg.get("item_list", []) or []:
        ref_msg = item.get("ref_msg") or {}
        message_item = ref_msg.get("message_item") or {}
        msg_id = message_item.get("msg_id")
        if msg_id:
            return str(msg_id)
    return ""


def _extract_ref_create_time_ms(msg: dict) -> int:
    """从 iLink 消息中提取被引用消息的创建时间戳（毫秒）。

    iLink sendmessage 响应体为空 {}，无法从中获取 msg_id，
    但引用回复的 ref_msg.message_item.create_time_ms 记录了被引用消息的时间戳。
    将其与 session 的 ilink_sent_at_ms 做近似匹配（±容差），
    可实现无 msg_id 场景下的精确会话定位。
    """
    for item in msg.get("item_list", []) or []:
        ref_msg = item.get("ref_msg") or {}
        message_item = ref_msg.get("message_item") or {}
        create_time_ms = message_item.get("create_time_ms")
        if create_time_ms:
            return int(create_time_ms)
    return 0


def _extract_ref_text(msg: dict) -> str:
    """从 iLink 引用回复中提取被引用消息的文本内容（L2 匹配，不稳定）。

    路径：item_list[].ref_msg.message_item.text_item.text

    iLink 并非每次都下发 text_item，但当它存在时，可直接从中提取
    [#short_id] 实现精确会话匹配，优于时间戳近似匹配（L1）。
    缺失时由调用方回退到 L1 时间戳匹配。
    """
    for item in msg.get("item_list", []) or []:
        ref_msg = item.get("ref_msg") or {}
        message_item = ref_msg.get("message_item") or {}
        text = (message_item.get("text_item") or {}).get("text") or ""
        if text:
            return text
    return ""


def _extract_quoted_text(msg: dict) -> str:
    """从 iLink 消息中提取被引用的原始消息文本（用于日志/调试）。

    提取优先级（从高到低）：
    1. ref_msg.message_item.text_item.text — iLink 标准引用结构（L2，有时缺失）
    2. refer_item.content / refer_item.text — 旧版或其他格式
    3. 嵌套 item_list — 部分版本 refer_item 内嵌原始消息结构
    4. refer_item.displayname — 最后兜底（发送方名称，不含 short_id）

    注意：displayname 是发送方显示名，不含 [#short_id] 标签，须放在最后。
    返回空字符串表示非引用回复或无法提取。
    """
    # 优先尝试新格式：ref_msg.message_item.text_item.text
    ref_text = _extract_ref_text(msg)
    if ref_text:
        return ref_text

    # 旧格式兜底：refer_item（某些版本/平台）
    for item in msg.get("item_list", []) or []:
        refer = item.get("refer_item") or {}
        if not refer:
            continue

        content = refer.get("content") or refer.get("text") or ""
        if not content:
            content = _extract_text(refer)
        if not content:
            content = refer.get("displayname") or ""
        if content:
            return content
    return ""


def _extract_short_id_from_refer(msg: dict) -> str | None:
    """从 iLink 引用回复的 refer_item 子树中提取 [#short_id]。

    iLink 引用回复时，被引用的原始消息（含我们注入的 [#short_id] 头部）保存在
    refer_item 内，但字段名因版本而异（content / displayname / text / ...），
    _extract_quoted_text 逐字段尝试容易漏。这里对整个 refer_item 子树做 JSON
    序列化后用正则搜索 [#short_id]，只要被引用原文完整保留了头部即可命中，
    不依赖具体字段名。
    """
    for item in msg.get("item_list", []) or []:
        refer = item.get("refer_item")
        if not refer:
            continue
        try:
            blob = json.dumps(refer, ensure_ascii=False)
        except Exception:
            continue
        m = _ILINK_SESSION_ID_RE.search(blob)
        if m:
            return m.group(1)
    return None


def _build_text_reply(context_token: str, text: str, to_user_id: str, message_id: int = 0) -> dict:
    item: dict = {"type": 1, "text_item": {"text": text}}
    msg: dict = {
        "context_token": context_token,
        "to_user_id": to_user_id,
        "from_user_id": "",
        "message_type": 2,
        "message_state": 2,
        "client_id": f"hil-{random.randint(0, 0xFFFFFFFF):x}",
        "item_list": [item],
    }
    # 顶层 message_id（i64）：iLink hub 的 ensure_outbound 仅当 message_id 为空时
    # 才自己分配；我方在此预设唯一值，hub 会保留，iLink 在用户引用回复时把它
    # 原样回传到 ref_msg.message_item.msg_id，从而实现 msg_id → session 精确匹配。
    if message_id:
        msg["message_id"] = message_id
    return msg


def _aes_128_ecb_encrypt(plaintext: bytes, key: bytes) -> bytes:
    """AES-128-ECB + PKCS7 padding 加密。

    iLink/微信 CDN 要求所有媒体文件用随机 AES-128 key 做 ECB 加密。
    """
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.padding import PKCS7

    padder = PKCS7(128).padder()
    padded = padder.update(plaintext) + padder.finalize()
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    encryptor = cipher.encryptor()
    return encryptor.update(padded) + encryptor.finalize()


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
                        "base_info": {"channel_version": "0.3.0", "bot_agent": "hitl-server-ilink/0.1.0"},
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
        quoted = _extract_quoted_text(msg)
        quoted_preview = repr(quoted[:40]) if quoted else "(无引用)"
        logger.info(
            f"[ilink-engine] 收到消息: user={from_user_id}, "
            f"text={text[:80]!r}, quoted={quoted_preview}"
        )

        if context_token and from_user_id:
            self.store.set_context_token(from_user_id, context_token)

        if from_user_id and text and self.on_message:
            await self.on_message(UserMessage(from_user_id, context_token, text, msg))

    async def send_message(self, to_user_id: str, text: str, outgoing_msg_id: int = 0) -> tuple[bool, Optional[str]]:
        """发送消息。返回 (success, msg_id_or_error)。

        成功时第二个元素是本条消息的 msg_id：优先回传我方设置的 outgoing_msg_id
        （顶层 message_id，i64 整数；iLink hub 仅当 message_id 为空时才自分配，
        我方预设后会被保留，并在用户引用回复时被 iLink 原样回传到
        ref_msg.message_item.msg_id，供精确匹配）；若未设置则尝试从响应体提取。
        失败时第二个元素是错误描述。
        """
        bot_token = self.store.get_bot_token()
        if not bot_token:
            return False, "未登录（无 bot_token）"
        context_token = self.store.get_context_token(to_user_id)
        if not context_token:
            return False, f"用户未激活: {to_user_id}"
        try:
            out_msg = _build_text_reply(context_token, text, to_user_id, outgoing_msg_id)
            res = await self._http.post(
                f"{self.base_url}/ilink/bot/sendmessage",
                headers=_ilink_headers(bot_token),
                json={
                    "msg": out_msg,
                    "base_info": {"channel_version": "0.3.0", "bot_agent": "hitl-server-ilink/0.1.0"},
                },
                timeout=15,
            )
            if res.status_code != 200:
                return False, f"HTTP {res.status_code}"
            raw = res.text
            # 我方已设置出站 message_id，直接以字符串回传（sendmessage 响应通常为空 {}）
            if outgoing_msg_id:
                return True, str(outgoing_msg_id)
            if not raw.strip():
                return True, ""
            data = res.json()
            logger.info(f"[ilink-engine] sendmessage 响应: {data}")
            if data.get("ret") not in (None, 0):
                return False, f"ret={data.get('ret')}, errmsg={data.get('errmsg')}"
            # 提取 iLink 分配的 msg_id（字段名可能是 msg_id / message_id）
            msg_id = str(data.get("msg_id") or data.get("message_id") or "")
            return True, msg_id
        except Exception as e:
            return False, str(e)

    # ── 发送图片 ───────────────────────────────────────────────────────────

    async def _upload_media(self, image_path: str, to_user_id: str) -> Optional[dict]:
        """加密图片 → getuploadurl → CDN POST，返回 sendmessage 所需的媒体参数。

        返回 dict 形如：
            { "encrypt_query_param": str, "aes_key": str(base64), "mid_size": int }
        失败返回 None 并记日志。

        协议参考：openclaw-weixin（hyonex）的 messenger.ts，已交叉验证字段名。
        """
        bot_token = self.store.get_bot_token()
        if not bot_token:
            logger.error("[ilink-engine] 发图失败：未登录（无 bot_token）")
            return None

        try:
            plaintext = Path(image_path).read_bytes()
        except Exception as e:
            logger.error(f"[ilink-engine] 读图片失败 {image_path}: {e}")
            return None

        aes_key = secrets.token_bytes(16)  # AES-128 → 16 字节
        filekey = secrets.token_hex(16)
        rawsize = len(plaintext)
        rawfilemd5 = hashlib.md5(plaintext).hexdigest()
        ciphertext = _aes_128_ecb_encrypt(plaintext, aes_key)
        ciphertext_size = len(ciphertext)

        try:
            # 1. getuploadurl
            res = await self._http.post(
                f"{self.base_url}/ilink/bot/getuploadurl",
                headers=_ilink_headers(bot_token),
                json={
                    "filekey": filekey,
                    "media_type": _MEDIA_TYPE_IMAGE,
                    "to_user_id": to_user_id,
                    "rawsize": rawsize,
                    "rawfilemd5": rawfilemd5,
                    "filesize": ciphertext_size,
                    "aeskey": aes_key.hex(),
                    "no_need_thumb": True,
                },
                timeout=15,
            )
            if res.status_code != 200:
                logger.error(f"[ilink-engine] getuploadurl HTTP {res.status_code}: {res.text[:200]}")
                return None
            upload_resp = res.json()
            if upload_resp.get("errcode") not in (None, 0):
                logger.error(
                    f"[ilink-engine] getuploadurl 失败: errcode={upload_resp.get('errcode')}, "
                    f"errmsg={upload_resp.get('errmsg')}"
                )
                return None

            upload_full_url = upload_resp.get("upload_full_url") or ""
            upload_param = upload_resp.get("upload_param") or ""
            if upload_full_url:
                upload_url = upload_full_url
            elif upload_param:
                upload_url = (
                    f"{_ILINK_CDN_BASE}/upload"
                    f"?encrypted_query_param={upload_param}"
                    f"&filekey={filekey}"
                )
            else:
                logger.error(f"[ilink-engine] getuploadurl 未返回上传地址: {upload_resp}")
                return None

            # 2. CDN POST 上传密文
            cdn_res = await self._http.post(
                upload_url,
                headers={
                    "Content-Type": "application/octet-stream",
                    "Content-Length": str(ciphertext_size),
                },
                content=ciphertext,
                timeout=30,
            )
            if cdn_res.status_code != 200:
                logger.error(f"[ilink-engine] CDN 上传 HTTP {cdn_res.status_code}: {cdn_res.text[:200]}")
                return None

            # 关键：encrypt_query_param 在响应头 x-encrypted-param，不在 body
            eqp = (
                cdn_res.headers.get("x-encrypted-param")
                or cdn_res.headers.get("X-Encrypted-Param")
                or ""
            )
            if not eqp:
                try:
                    j = cdn_res.json()
                    eqp = j.get("encrypted_query_param") or j.get("encrypt_query_param") or ""
                except Exception:
                    pass
            if not eqp:
                logger.error("[ilink-engine] CDN 上传后未拿到 encrypt_query_param")
                return None

            # aes_key 给 API 时是 base64(hex_string)——注意不是直接 base64(key)
            aes_key_for_api = base64.b64encode(aes_key.hex().encode()).decode()

            return {
                "encrypt_query_param": eqp,
                "aes_key": aes_key_for_api,
                "mid_size": ciphertext_size,
            }
        except Exception as e:
            logger.error(f"[ilink-engine] 上传图片失败: {e}", exc_info=True)
            return None

    def _build_image_reply(
        self, context_token: str, to_user_id: str, media: dict, caption: str = ""
    ) -> dict:
        """构造图片消息体。可选 caption 会作为 text_item 放在图片前。"""
        items: list[dict] = []
        if caption:
            items.append({"type": 1, "text_item": {"text": caption}})
        items.append({
            "type": _ITEM_TYPE_IMAGE,
            "image_item": {
                "media": {
                    "encrypt_query_param": media["encrypt_query_param"],
                    "aes_key": media["aes_key"],
                    "encrypt_type": 1,
                },
                "mid_size": media["mid_size"],
            },
        })
        return {
            "context_token": context_token,
            "to_user_id": to_user_id,
            "from_user_id": "",
            "message_type": 2,
            "message_state": 2,
            "client_id": f"hil-{random.randint(0, 0xFFFFFFFF):x}",
            "item_list": items,
        }

    async def send_image(
        self, to_user_id: str, image_path: str, caption: str = ""
    ) -> tuple[bool, Optional[str]]:
        """发送图片消息。返回 (success, error_or_none)。

        先上传图片到 CDN，再发 sendmessage。
        """
        bot_token = self.store.get_bot_token()
        if not bot_token:
            return False, "未登录（无 bot_token）"
        context_token = self.store.get_context_token(to_user_id)
        if not context_token:
            return False, f"用户未激活: {to_user_id}"

        media = await self._upload_media(image_path, to_user_id)
        if not media:
            return False, "图片上传 CDN 失败"

        try:
            msg = self._build_image_reply(context_token, to_user_id, media, caption)
            res = await self._http.post(
                f"{self.base_url}/ilink/bot/sendmessage",
                headers=_ilink_headers(bot_token),
                json={
                    "msg": msg,
                    "base_info": {"channel_version": "0.3.0", "bot_agent": "hitl-server-ilink/0.1.0"},
                },
                timeout=15,
            )
            if res.status_code != 200:
                return False, f"HTTP {res.status_code}"
            raw = res.text
            if not raw.strip():
                return True, None
            data = res.json()
            if data.get("ret") not in (None, 0) or data.get("errcode") not in (None, 0):
                return False, f"ret={data.get('ret')}, errcode={data.get('errcode')}, errmsg={data.get('errmsg')}"
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


# ── 消息头拼接 ─────────────────────────────────────────────────────────────

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
    """转成 fly-pigeon 兼容结构，供 storage.handle_callback 消费。

    iLink 引用回复匹配策略（按优先级，由 storage 侧消费）：
    - ref_msg_id（最强精确）：ref_msg.message_item.msg_id == 我方出站设置的 msg_id → data["ref_msg_id"]
    - engine short_id：refer_item 子树正则提取 → data["short_id"]
    - L2（精确）：ref_msg.message_item.text_item.text → ref_text 字段
    - L1（近似）：ref_msg.message_item.create_time_ms → ref_create_time_ms 字段
    - quote：_extract_quoted_text 提取的引用文本（兼容 wecom / 旧 refer_item 格式）
    """
    data: dict = {
        "chatid": msg.from_user_id,
        "chattype": "single",
        "msgtype": "text",
        "text": {"content": msg.text},
        "from": {"userid": msg.from_user_id, "name": ""},
    }
    # 最强精确：被引用消息的 msg_id（等于我方出站时设置的 msg_id）
    ref_msg_id = _extract_ref_msg_id(msg.raw)
    if ref_msg_id:
        data["ref_msg_id"] = ref_msg_id
        logger.debug(f"[ilink-engine] 提取 ref_msg_id: {ref_msg_id}")

    # L2: 被引用消息文本（iLink 不稳定下发，存在时可提取 [#short_id] 精确匹配）
    ref_text = _extract_ref_text(msg.raw)
    if ref_text:
        data["ref_text"] = ref_text
        logger.debug(f"[ilink-engine] 提取引用文本(L2): {ref_text[:80]!r}")

    # L1: 时间戳近似匹配（无 text_item 时的回退手段）
    ref_create_time_ms = _extract_ref_create_time_ms(msg.raw)
    if ref_create_time_ms:
        data["ref_create_time_ms"] = ref_create_time_ms
        logger.debug(f"[ilink-engine] 提取引用时间戳(L1): {ref_create_time_ms}")

    quoted_text = _extract_quoted_text(msg.raw)
    if quoted_text:
        data["quote"] = {
            "msgtype": "text",
            "text": {"content": quoted_text},
        }
        logger.debug(f"[ilink-engine] 提取引用文本(quote): {quoted_text[:80]!r}")

    refer_short_id = _extract_short_id_from_refer(msg.raw)
    if refer_short_id:
        data["short_id"] = refer_short_id
        logger.info(f"[ilink-engine] 从 refer_item 子树提取 short_id={refer_short_id}")
    else:
        # 存在引用却未提取到 short_id：打印 refer_item 结构便于排查字段名差异
        for item in msg.raw.get("item_list", []) or []:
            if item.get("refer_item"):
                logger.info(f"[ilink-engine] refer_item 未提取到 short_id，原始结构: {item!r}")
    return data


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
                result = await self.on_user_message(callback_data)
                if isinstance(result, dict) and result.get("prompt_user"):
                    # 多个等待中的会话且用户未引用回复，无法自动路由
                    # → 发送提示，引导用户长按引用目标消息后再回复
                    waiting_ids = result.get("waiting_short_ids", [])
                    prompt = (
                        f"⚠️ 有 {len(waiting_ids)} 条待回复的请求，无法自动匹配。\n"
                        "请长按目标消息 → 引用回复，以确保路由到正确的对话：\n"
                        + "\n".join(f"  [#{sid}]" for sid in waiting_ids)
                    )
                    ok, err = await self.client.send_message(msg.from_user_id, prompt)
                    if not ok:
                        logger.warning(f"[ilink-engine] 发送引用提示失败: {err}")
                    else:
                        logger.info(f"[ilink-engine] 已发送引用提示: waiting_ids={waiting_ids}")
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
        images: list[str] = payload.get("images") or []

        if not chat_id:
            chat_id = self.store.resolve_recipient() or ""
        if not chat_id:
            return {"success": False, "error": "尚无已激活用户，无法发送"}
        if not self.client.is_logged_in:
            return {"success": False, "error": "login_required"}

        formatted = _format_message_with_header(message, short_id, project_name, wait_reply)
        # 生成出站顶层 message_id（i64 整数）：iLink hub 的 ensure_outbound 仅当
        # message_id 为空时才自分配，我方预设后会被保留，并在用户引用回复时被
        # iLink 原样回传到 ref_msg.message_item.msg_id，据此做 msg_id → session
        # 精确匹配（突破并发歧义）。结构对齐 hub 的 new_outbound_msg_id：
        # unix_millis * 1_000_000 + counter，量级 ~1.78e18，远小于 i64::MAX(9.22e18)，
        # 在 iLink 已验证会原样保留的区间内。
        outgoing_msg_id = int(time.time() * 1000) * 1_000_000 + random.randint(0, 999_999)
        sent_at_ms = int(time.time() * 1000)
        ok, msg_id_or_err = await self.client.send_message(chat_id, formatted, outgoing_msg_id)
        if not ok:
            return {"success": False, "chat_id": None, "error": msg_id_or_err}

        # 发送附带的图片（每张一条独立消息）。文字消息承载 [#short_id] 头部用于
        # 会话匹配，图片紧随其后发出；图片失败不中断整体流程，仅记日志。
        for img_path in images:
            try:
                img_ok, img_err = await self.client.send_image(chat_id, img_path)
                if not img_ok:
                    logger.warning(f"[ilink-engine] 发送图片失败 {img_path}: {img_err}")
                else:
                    logger.info(f"[ilink-engine] 图片已发送: {img_path}")
            except Exception as e:
                logger.warning(f"[ilink-engine] 发送图片异常 {img_path}: {e}")

        return {
            "success": True,
            "chat_id": chat_id,
            "ilink_msg_id": msg_id_or_err or "",
            "ilink_sent_at_ms": sent_at_ms,
        }

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
            "base_url": self.client.base_url,
        }
