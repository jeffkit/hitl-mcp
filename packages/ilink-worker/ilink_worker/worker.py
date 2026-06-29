"""iLink Worker 主程序。

职责：
- 维持一条到 HIL Server 的 WebSocket 连接，注册为 worker_type=ilink
- 后台跑 iLink 长轮询（ILinkClient），收到用户消息后转成 fly-pigeon 兼容结构上报 Server
- 处理 Server 下行的 request：
    send_message          — 向微信用户发消息
    send_hint             — 发提示消息（与 send_message 同路径）
    get_qr                — 获取扫码二维码（方案 B）
    get_login_status      — 查询登录状态
    list_activated_users  — 列出已激活用户

运行：
    python -m ilink_worker.worker
"""
import asyncio
import json
import logging
import socket
from urllib.parse import urlencode

import websockets

from .config import config
from .token_store import TokenStore
from .ilink_client import ILinkClient, UserMessage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def _to_callback_data(msg: UserMessage) -> dict:
    """把 iLink 用户消息转成 fly-pigeon 回调兼容结构，供 storage.handle_callback 消费。

    handle_callback / extract_reply_from_callback 识别的字段：
      chatid / chattype / msgtype / text.content / from.userid / quote
    """
    return {
        "chatid": msg.from_user_id,
        "chattype": "single",
        "msgtype": "text",
        "text": {"content": msg.text},
        "from": {"userid": msg.from_user_id, "name": ""},
    }


def _format_message_with_header(
    message: str,
    short_id: str,
    project_name: str | None = None,
    wait_reply: bool = True,
) -> str:
    """给下行消息加会话头和回复提示。

    iLink 走个人微信单聊，是纯文本通道（不支持 markdown），所以 footer 用纯文本。
    - 有 short_id 才加头：[#short_id 项目名] / [#short_id]（与 HIL Server / devcloud-worker 一致）
    - wait_reply=True 才加「📮 请回复」footer
    - 提示消息（short_id 为空、wait_reply=False）原样发送，不加头不加尾
    """
    parts: list[str] = []
    if short_id:
        parts.append(f"[#{short_id} {project_name}]" if project_name else f"[#{short_id}]")
    parts.append(message)
    body = "\n".join(parts)
    if wait_reply:
        body = f"{body}\n\n📮 请回复"
    return body


class ILinkWorker:
    def __init__(self):
        self.store = TokenStore(config.token_store_path)
        self.client = ILinkClient(
            base_url=config.ilink_base_url,
            token_store=self.store,
            poll_timeout=config.poll_timeout,
        )
        self.client.on_message = self._on_user_message
        self._ws = None
        self._send_lock = asyncio.Lock()
        self._running = False
        self._reconnect_delay = config.reconnect_delay
        self._pending_tasks: set = set()

    # ── WebSocket 收发 ────────────────────────────────────────
    async def _send(self, message: dict) -> None:
        if self._ws:
            try:
                async with self._send_lock:
                    await self._ws.send(json.dumps(message))
            except Exception as e:
                logger.warning(f"WS 发送失败: {e}")

    async def _send_response(self, request_id: str, success: bool, data: dict | None = None, error: str | None = None) -> None:
        await self._send({"type": "response", "id": request_id, "success": success, "data": data or {}, "error": error})

    async def _register(self) -> None:
        try:
            hostname = socket.gethostname()
            ip_address = socket.gethostbyname(hostname)
        except Exception:
            hostname, ip_address = "unknown", "unknown"

        info = {
            "worker_id": config.worker_id,
            "worker_type": config.worker_type,  # ilink
            "bot_key": config.bot_key,
            "ip_address": ip_address,
            "hostname": hostname,
            "hil_url": config.hil_url,
            "config_file": config.config_file,
        }
        await self._send({"type": "register", "worker_info": info})
        logger.info(f"已注册为 iLink Worker: id={config.worker_id}, bot_key={config.bot_key}")

    async def _connect(self) -> None:
        params = {"worker_id": config.worker_id, "token": config.hil_token}
        url = f"{config.hil_url}?{urlencode(params)}"
        logger.info(f"连接 HIL Server: {url}")
        self._ws = await websockets.connect(
            url, ping_interval=None, ping_timeout=None, close_timeout=10,
        )
        logger.info("WebSocket 连接成功")
        self._reconnect_delay = config.reconnect_delay
        await self._register()

    # ── 上行：用户消息 → HIL Server callback ──────────────────
    async def _on_user_message(self, msg: UserMessage) -> None:
        callback_data = _to_callback_data(msg)
        payload = {
            "type": "callback",
            "event": "user_message",
            "worker_type": config.worker_type,
            "bot_key": config.bot_key,
            "data": {"callback_data": callback_data},
        }
        await self._send(payload)
        logger.info(f"已上报用户消息: user={msg.from_user_id}")

    # ── 下行：处理 Server 请求 ────────────────────────────────
    async def _handle_request(self, message: dict) -> None:
        request_id = message.get("id")
        action = message.get("action")
        payload = message.get("payload", {}) or {}
        logger.info(f"收到请求: id={request_id}, action={action}")
        try:
            if action == "send_message":
                await self._action_send_message(request_id, payload)
            elif action == "send_hint":
                # 提示消息与普通消息同走 sendmessage
                await self._action_send_message(request_id, payload)
            elif action == "get_qr":
                result = await self.client.get_qr()
                ok = result.get("status") != "error"
                await self._send_response(request_id, ok, result, None if ok else result.get("error"))
            elif action == "get_login_status":
                await self._send_response(request_id, True, {"status": self.client.login_status})
            elif action == "list_activated_users":
                await self._send_response(request_id, True, {"users": self.store.list_known_users()})
            else:
                await self._send_response(request_id, False, error=f"Unknown action: {action}")
        except Exception as e:
            logger.error(f"处理请求失败: {e}", exc_info=True)
            await self._send_response(request_id, False, error=str(e))

    async def _action_send_message(self, request_id: str, payload: dict) -> None:
        chat_id = payload.get("chat_id", "") or ""
        message = payload.get("message", "") or ""
        short_id = payload.get("short_id", "") or ""
        project_name = payload.get("project_name") or None
        wait_reply = bool(payload.get("wait_reply", True))
        if not chat_id:
            chat_id = self.store.resolve_recipient() or ""
        if not chat_id:
            await self._send_response(request_id, False, error="尚无已激活用户，无法发送")
            return
        if not self.client.is_logged_in:
            await self._send_response(request_id, False, error="login_required")
            return
        formatted = _format_message_with_header(message, short_id, project_name, wait_reply)
        ok, err = await self.client.send_message(chat_id, formatted)
        # 回传实际使用的 chat_id（收件人 openid），供 HIL Server 关联到 session，
        # 使 iLink 1:1 模型下用户回复时能按 chat_id 匹配到等待中的会话。
        await self._send_response(
            request_id, ok, {"sent": ok, "chat_id": chat_id}, None if ok else err
        )

    # ── 主循环 ────────────────────────────────────────────────
    async def run(self) -> None:
        self._running = True
        await self.client.start()

        while self._running:
            try:
                await self._connect()
                hb_timeout = config.heartbeat_timeout
                while self._ws:
                    try:
                        data = await asyncio.wait_for(self._ws.recv(), timeout=hb_timeout)
                        message = json.loads(data)
                        mtype = message.get("type")
                        if mtype == "ping":
                            await self._send({"type": "pong"})
                        elif mtype == "request":
                            task = asyncio.create_task(self._handle_request(message))
                            self._pending_tasks.add(task)
                            task.add_done_callback(self._pending_tasks.discard)
                        else:
                            logger.warning(f"未知消息类型: {mtype}")
                    except asyncio.TimeoutError:
                        logger.warning("心跳超时，主动断开重连")
                        if self._ws:
                            await self._ws.close()
                        break
                    except json.JSONDecodeError:
                        logger.warning("无效 JSON")
                    except websockets.ConnectionClosed as e:
                        # 连接已关闭（新版 websockets 抛 ConnectionClosedError，属于此类）
                        logger.warning(f"WebSocket 连接已关闭: {e}")
                        break
                    except Exception as e:
                        logger.error(f"处理消息失败: {e}", exc_info=True)
                        # 兜底：若是连接类异常，跳出以触发重连
                        if self._ws is None or self._ws.closed:
                            break
            except websockets.ConnectionClosed:
                logger.warning("WebSocket 连接已关闭")
            except Exception as e:
                logger.error(f"WebSocket 错误: {e}", exc_info=True)
            finally:
                self._ws = None
                if self._pending_tasks:
                    await asyncio.gather(*self._pending_tasks, return_exceptions=True)
                    self._pending_tasks.clear()

            if self._running:
                logger.info(f"{self._reconnect_delay}s 后重连...")
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, config.max_reconnect_delay)

    def stop(self) -> None:
        self._running = False


worker = ILinkWorker()


def main():
    try:
        asyncio.run(worker.run())
    except KeyboardInterrupt:
        worker.stop()


if __name__ == "__main__":
    main()
