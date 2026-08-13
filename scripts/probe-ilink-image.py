#!/usr/bin/env python3
"""iLink 发图探针脚本 —— 阶段 0.1b

用真实 iLink 凭证（~/.hil-mcp/ilink_store.json）跑通完整发图链路：
  读图 → AES-128-ECB 加密 → getuploadurl → CDN POST → sendmessage

目的：验证从 hyonex/openclaw-weixin 逆向来的协议 schema 是否正确，
为 hil-mcp 的 ILinkClient.send_image 实现提供经过实测的代码模板。

用法：
  python3 scripts/probe-ilink-image.py <图片路径> [to_user_id]

若不传 to_user_id，用 ilink_store.json 里第一个已激活用户。
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import sys
from pathlib import Path

import httpx
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

# ── 配置 ────────────────────────────────────────────────────────────────

BASE_URL = "https://ilinkai.weixin.qq.com"
TOKEN_STORE = Path.home() / ".hil-mcp" / "ilink_store.json"
UA = "Mozilla/5.0 (compatible; iLink-Bot/1.0)"

# iLink 协议常量（来自 openclaw-weixin types.ts）
MEDIA_IMAGE = 1
ITEM_IMAGE = 2
MSG_TYPE_BOT = 2
MSG_STATE_FINISH = 2

CDN_BASE_URL = "https://novac2c.cdn.weixin.qq.com/c2c"


# ── 工具函数 ────────────────────────────────────────────────────────────

def random_uin() -> str:
    """模拟 X-WECHAT-UIN（随机 uint32 的 base64）。"""
    import random
    return base64.b64encode(str(random.randint(0, 0xFFFFFFFF)).encode()).decode()


def ilink_headers(bot_token: str) -> dict[str, str]:
    return {
        "AuthorizationType": "ilink_bot_token",
        "Authorization": f"Bearer {bot_token}",
        "Content-Type": "application/json",
        "User-Agent": UA,
        "X-WECHAT-UIN": random_uin(),
    }


def aes_128_ecb_encrypt(plaintext: bytes, key: bytes) -> bytes:
    """AES-128-ECB + PKCS7 padding 加密。"""
    padder = PKCS7(128).padder()
    padded = padder.update(plaintext) + padder.finalize()
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    encryptor = cipher.encryptor()
    return encryptor.update(padded) + encryptor.finalize()


# ── 发图链路 ────────────────────────────────────────────────────────────

def upload_media(
    client: httpx.Client,
    image_path: str,
    to_user_id: str,
    bot_token: str,
) -> dict:
    """加密图片 → getuploadurl → CDN POST，返回 sendmessage 所需的媒体参数。"""
    plaintext = Path(image_path).read_bytes()
    aes_key = secrets.token_bytes(16)  # AES-128 → 16 字节 key
    filekey = secrets.token_hex(16)
    rawsize = len(plaintext)
    rawfilemd5 = hashlib.md5(plaintext).hexdigest()

    # 先加密，拿到密文长度（filesize 要传密文大小，不是原文）
    ciphertext = aes_128_ecb_encrypt(plaintext, aes_key)
    ciphertext_size = len(ciphertext)

    print(f"[1/4] 图片: {image_path}")
    print(f"      原文 {rawsize}B → 密文 {ciphertext_size}B, md5={rawfilemd5[:16]}...")
    print(f"      aes_key(hex)={aes_key.hex()[:32]}")

    # ── getuploadurl ──
    body = {
        "filekey": filekey,
        "media_type": MEDIA_IMAGE,
        "to_user_id": to_user_id,
        "rawsize": rawsize,
        "rawfilemd5": rawfilemd5,
        "filesize": ciphertext_size,
        "aeskey": aes_key.hex(),
        "no_need_thumb": True,
    }
    print(f"[2/4] POST /ilink/bot/getuploadurl ...")
    res = client.post(
        f"{BASE_URL}/ilink/bot/getuploadurl",
        headers=ilink_headers(bot_token),
        json=body,
        timeout=15,
    )
    print(f"      HTTP {res.status_code}")
    res.raise_for_status()
    upload_resp = res.json()
    print(f"      响应: {json.dumps(upload_resp, ensure_ascii=False)[:200]}")

    upload_full_url = upload_resp.get("upload_full_url") or ""
    upload_param = upload_resp.get("upload_param") or ""

    if upload_full_url:
        upload_url = upload_full_url
    elif upload_param:
        upload_url = (
            f"{CDN_BASE_URL}/upload"
            f"?encrypted_query_param={upload_param}"
            f"&filekey={filekey}"
        )
    else:
        raise RuntimeError(f"getuploadurl 未返回上传地址: {upload_resp}")

    # ── CDN POST 上传密文 ──
    print(f"[3/4] POST CDN (密文 {ciphertext_size}B) ...")
    print(f"      url={upload_url[:100]}...")
    cdn_res = client.post(
        upload_url,
        headers={
            "Content-Type": "application/octet-stream",
            "Content-Length": str(ciphertext_size),
        },
        content=ciphertext,
        timeout=30,
    )
    print(f"      HTTP {cdn_res.status_code}")

    # 关键：encrypt_query_param 在响应头 x-encrypted-param，不在 body
    eqp = (
        cdn_res.headers.get("x-encrypted-param")
        or cdn_res.headers.get("X-Encrypted-Param")
        or ""
    )
    if not eqp:
        # 兜底从 body 取
        try:
            j = cdn_res.json()
            eqp = j.get("encrypted_query_param") or j.get("encrypt_query_param") or ""
        except Exception:
            pass
    print(f"      encrypt_query_param={eqp[:50] + '...' if eqp else 'EMPTY ❌'}")
    if not eqp:
        print(f"      [警告] CDN body: {cdn_res.text[:300]}")
        print(f"      [警告] CDN headers: {dict(cdn_res.headers)}")
        raise RuntimeError("CDN 上传后未拿到 encrypt_query_param")

    # aes_key 给 API 时是 base64(hex_string)
    aes_key_for_api = base64.b64encode(aes_key.hex().encode()).decode()

    return {
        "encrypt_query_param": eqp,
        "aes_key": aes_key_for_api,
        "mid_size": ciphertext_size,
    }


def send_image_message(
    client: httpx.Client,
    to_user_id: str,
    context_token: str,
    bot_token: str,
    media: dict,
    caption: str = "",
) -> dict:
    """发送图片消息。"""
    items = []
    if caption:
        items.append({"type": 1, "text_item": {"text": caption}})
    items.append({
        "type": ITEM_IMAGE,
        "image_item": {
            "media": {
                "encrypt_query_param": media["encrypt_query_param"],
                "aes_key": media["aes_key"],
                "encrypt_type": 1,
            },
            "mid_size": media["mid_size"],
        },
    })

    import random
    msg = {
        "context_token": context_token,
        "to_user_id": to_user_id,
        "from_user_id": "",
        "message_type": MSG_TYPE_BOT,
        "message_state": MSG_STATE_FINISH,
        "client_id": f"probe-{random.randint(0, 0xFFFFFFFF):x}",
        "item_list": items,
    }

    print(f"[4/4] POST /ilink/bot/sendmessage (item_list={len(items)} 项)")
    print(f"      image_item 样例: {json.dumps(items[-1], ensure_ascii=False)[:200]}")
    res = client.post(
        f"{BASE_URL}/ilink/bot/sendmessage",
        headers=ilink_headers(bot_token),
        json={
            "msg": msg,
            "base_info": {"channel_version": "0.3.0", "bot_agent": "hitl-probe/0.1"},
        },
        timeout=15,
    )
    print(f"      HTTP {res.status_code}")
    print(f"      body: {res.text[:300]}")
    res.raise_for_status()
    return res.json() if res.text.strip() else {}


# ── 主流程 ──────────────────────────────────────────────────────────────

def main() -> int:
    if len(sys.argv) < 2:
        print(f"用法: {sys.argv[0]} <图片路径> [to_user_id]", file=sys.stderr)
        return 2

    image_path = sys.argv[1]
    if not os.path.exists(image_path):
        print(f"图片不存在: {image_path}", file=sys.stderr)
        return 2

    # 读凭证
    store = json.loads(TOKEN_STORE.read_text(encoding="utf-8"))
    bot_token = store.get("bot_token")
    if not bot_token:
        print("ilink_store.json 没有 bot_token，请先扫码登录", file=sys.stderr)
        return 1

    context_tokens = store.get("context_tokens") or {}
    if len(sys.argv) >= 3:
        to_user_id = sys.argv[2]
    else:
        to_user_id = next(iter(context_tokens), "")
    if not to_user_id or to_user_id not in context_tokens:
        print(f"未找到已激活用户。已知: {list(context_tokens)}", file=sys.stderr)
        return 1
    context_token = context_tokens[to_user_id]

    print(f"目标用户: {to_user_id}")
    print(f"bot_token: {bot_token[:16]}...")
    print("=" * 60)

    with httpx.Client() as client:
        media = upload_media(client, image_path, to_user_id, bot_token)
        print("-" * 60)
        result = send_image_message(
            client, to_user_id, context_token, bot_token, media,
            caption="🔬 hil-mcp 发图探针测试（请忽略）",
        )
    print("=" * 60)
    print("✅ 发送完成！请检查微信是否收到图片。")
    print(f"sendmessage 响应: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
