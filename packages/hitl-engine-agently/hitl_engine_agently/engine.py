"""Agently Mail（QQ Agent 邮箱）HITL 引擎。

与 telegram 引擎同构的轮询式渠道，但上游从 Bot API 换成本机 ``agently-cli``：

- 下行 ``send_message``：主题以 ``[#short_id 项目名]`` 开头（回复引用主题即可
  精确匹配会话），正文附回复指引；CLI 两阶段确认在 :mod:`.cli` 内自动完成。
- 上行轮询：``message +list``（收件箱）→ 首轮建档（不触发历史邮件）→
  增量消息按「发件人 ACL + [#short_id] 标签」筛出 HITL 回复 →
  ``+read`` 取正文（HTML 剥壳）→ 转 fly-pigeon 兼容结构交
  ``storage.handle_callback``。
- 安全：非 ACL 发件人携带标记的邮件只记已读不回灌（防伪造发件人触发会话）；
  邮件正文属外部不可信输入，引擎只做文本搬运，不做任何指令解释。

退出码 3（授权失效）不停止轮询：管理员重新 ``agently-cli auth login`` 后
下一轮自动恢复；status() 以 ``auth_ok=false`` 呈现降级态。
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from hitl_server.engines.base import BaseEngine
from hitl_server.engines.registry import EngineContext, EngineDescriptor

from .cli import AgentlyCli, AgentlyCliError, html_to_text
from .store import DEFAULT_STORE_DIR, AgentlyMailStore

logger = logging.getLogger(__name__)

WORKER_TYPE = "agently-mail"

#: 与 telegram 引擎一致的 short-id 提取规则：`[#a1b2c3d4 可选项目名]`
_SHORT_ID_RE = re.compile(r"\[#([a-f0-9]{8,12})(?:\s+[^\]]+)?\]")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

REPLY_HINT = "> 请直接回复本邮件（保留主题中的 [#{sid}] 标记），回复内容将作为该请求的确认结果。"


def _extract_short_id(text: str) -> Optional[str]:
    m = _SHORT_ID_RE.search(text or "")
    return m.group(1) if m else None


def _norm_email(addr: str) -> str:
    return (addr or "").strip().lower()


class AgentlyMailEngine(BaseEngine):
    """经 agently-cli 收发确认邮件的引擎。"""

    WORKER_TYPE = WORKER_TYPE

    def __init__(
        self,
        bot_key: str,
        cli: AgentlyCli,
        store: AgentlyMailStore,
        default_recipient: str,
        allowed_senders: List[str],
        poll_interval: float = 60.0,
    ):
        super().__init__(worker_type=self.WORKER_TYPE, bot_key=bot_key)
        self._cli = cli
        self._store = store
        self._default_recipient = _norm_email(default_recipient)
        self._allowed = {_norm_email(a) for a in (allowed_senders or [default_recipient])}
        self._poll_interval = max(30.0, float(poll_interval))
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._seen = store.get_seen()
        self._baseline_done = store.is_baseline_done()
        # 状态展示
        self._last_poll_at: Optional[str] = None
        self._last_error: Optional[str] = None
        self._auth_ok: Optional[bool] = None
        self._account_email: Optional[str] = None
        self._sent_count = 0

    # ── 生命周期 ────────────────────────────────────────────────────────────

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info(
            f"[agently-mail-engine] 轮询已启动 (bot_key={self.bot_key}, "
            f"recipient={self._default_recipient}, interval={self._poll_interval:.0f}s)"
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        logger.info(f"[agently-mail-engine] 已停止 (bot_key={self.bot_key})")

    # ── 上行：轮询收件箱 ─────────────────────────────────────────────────────

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                await self._poll_once()
                self._last_error = None
            except AgentlyCliError as e:
                self._last_error = f"exit={e.code}: {e.message}"
                if e.code == 3:
                    self._auth_ok = False
                    logger.warning("[agently-mail-engine] 授权失效，请重新 `agently-cli auth login`")
                else:
                    logger.warning(f"[agently-mail-engine] 轮询异常: {e}")
            except asyncio.CancelledError:
                return
            except Exception as e:  # 防轮询循环意外退出
                self._last_error = str(e)
                logger.error(f"[agently-mail-engine] 轮询未预期异常: {e}", exc_info=True)
            await asyncio.sleep(self._poll_interval)

    async def _poll_once(self) -> None:
        self._last_poll_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        msgs = await self._cli.list_inbox(limit=20)

        if not self._baseline_done:
            # 首轮只建档：存量邮件不当作回复，避免引擎启动瞬间回灌历史
            self._seen.update(m.get("message_id", "") for m in msgs)
            self._store.add_seen([m.get("message_id", "") for m in msgs if m.get("message_id")])
            self._baseline_done = True
            self._store.mark_baseline_done()
            logger.info(f"[agently-mail-engine] 基线建档完成，存量 {len(msgs)} 封不触发")
            return

        fresh = [m for m in msgs if m.get("message_id") and m["message_id"] not in self._seen]
        if fresh:
            self._seen.update(m["message_id"] for m in fresh)
            self._store.add_seen([m["message_id"] for m in fresh])

        for msg in fresh:
            await self._handle_inbox_message(msg)

    async def _handle_inbox_message(self, msg: dict) -> None:
        mid = msg.get("message_id", "")
        sender = _norm_email((msg.get("from") or {}).get("email"))
        subject = msg.get("subject") or ""
        sid = _extract_short_id(subject) or _extract_short_id(msg.get("snippet") or "")

        if not sid:
            return  # 与 HITL 无关的普通邮件，只记已见

        if self._allowed and sender not in self._allowed:
            logger.warning(
                f"[agently-mail-engine] 拒绝非白名单发件人的标记邮件: {sender or '<unknown>'} "
                f"(mid={mid[:24]}…, sid={sid})——疑似伪造，已忽略"
            )
            return

        # 取正文（HTML 剥壳）；读失败时降级用 snippet，不丢回复
        text = ""
        try:
            full = await self._cli.read(mid)
            body = full.get("body") or ""
            if (full.get("body_format") or "").upper() == "HTML":
                text = html_to_text(body)
            else:
                text = body.strip()
        except Exception as e:
            logger.warning(f"[agently-mail-engine] 读取回复正文失败（降级用摘要）: {e}")
        if not text:
            text = (msg.get("snippet") or "").strip()

        callback_data: Dict[str, Any] = {
            "chatid": sender or self._default_recipient,
            "chattype": "single",
            "msgtype": "text",
            "text": {"content": text},
            "from": {
                "userid": sender or "unknown",
                "name": (msg.get("from") or {}).get("name") or sender,
            },
            "short_id": sid,
            "raw_agently_message": {
                "message_id": mid,
                "subject": subject,
                "from": msg.get("from"),
                "created_at": msg.get("created_at"),
            },
        }
        logger.info(f"[agently-mail-engine] 收到回复: from={sender}, sid={sid}, text={text[:60]!r}")
        if self.on_user_message:
            try:
                await self.on_user_message(callback_data)
            except Exception as e:
                logger.error(f"[agently-mail-engine] 回灌会话失败: {e}", exc_info=True)

    # ── 下行：发送确认请求 ───────────────────────────────────────────────────

    async def send_message(self, payload: dict) -> dict:
        message = payload.get("message") or ""
        short_id = payload.get("short_id") or ""
        project_name = payload.get("project_name") or None
        wait_reply = bool(payload.get("wait_reply", True))
        chat_id = _norm_email(payload.get("chat_id") or "") or self._default_recipient

        if not chat_id:
            return {"success": False, "error": "default_recipient 未配置（启动引擎时必填审批人邮箱）"}

        head = f"[#{short_id} {project_name}]" if (short_id and project_name) else f"[#{short_id}]"
        subject = f"{head} HITL 确认请求".strip()
        body = message.strip()
        if wait_reply and short_id:
            body = f"{body}\n\n{REPLY_HINT.format(sid=short_id)}"

        try:
            await self._cli.send(to=[chat_id], subject=subject, body=body)
        except AgentlyCliError as e:
            if e.code == 3:
                self._auth_ok = False
            return {"success": False, "error": f"agently-cli exit={e.code}: {e.message}"}

        self._sent_count += 1
        self._auth_ok = True
        logger.info(f"[agently-mail-engine] 已发送确认请求: to={chat_id}, sid={short_id}")
        return {"success": True, "chat_id": chat_id}

    # ── 状态 ────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "worker_type": self.WORKER_TYPE,
            "bot_key": self.bot_key,
            "running": self._running,
            "account_email": self._account_email,
            "recipient": self._default_recipient,
            "allowed_senders": sorted(self._allowed),
            "poll_interval_seconds": self._poll_interval,
            "last_poll_at": self._last_poll_at,
            "last_error": self._last_error,
            "auth_ok": self._auth_ok,
            "sent_count": self._sent_count,
        }

    async def refresh_account(self) -> None:
        """刷新账号信息（管理台/诊断用；失败不影响轮询）。"""
        try:
            data = await self._cli.me()
            aliases = data.get("aliases") or []
            primary = next((a for a in aliases if a.get("is_primary")), None)
            self._account_email = (primary or (aliases[0] if aliases else {})).get("email")
            self._auth_ok = True
        except Exception as e:
            self._auth_ok = False
            self._last_error = f"+me: {e}"


# ════════════════════ EngineDescriptor 装配 ════════════════════

def _store_path(bot_key: str, override: Optional[str] = None) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", bot_key) or "default"
    return override or os.path.join(DEFAULT_STORE_DIR, f"agently_mail_{safe}.json")


def _normalize_senders(raw: Any, default_recipient: str) -> List[str]:
    default = _norm_email(default_recipient)
    if raw is None or raw == "":
        return [default]
    if isinstance(raw, str):
        items = [x for x in (s.strip() for s in raw.split(",")) if x]
    elif isinstance(raw, list):
        items = [str(x).strip() for x in raw if str(x).strip()]
    else:
        items = []
    senders = [_norm_email(x) for x in items]
    if default not in senders:
        senders.append(default)
    return senders


def _build_engine(bot_key: str, params: Dict[str, Any]) -> AgentlyMailEngine:
    default_recipient = _norm_email(str(params.get("default_recipient") or ""))
    return AgentlyMailEngine(
        bot_key=bot_key,
        cli=AgentlyCli(cli_path=str(params.get("cli_path") or "agently-cli")),
        store=AgentlyMailStore(_store_path(bot_key, params.get("store_path"))),
        default_recipient=default_recipient,
        allowed_senders=_normalize_senders(params.get("allowed_senders"), default_recipient),
        poll_interval=float(params.get("poll_interval_seconds") or 60),
    )


async def _build_startup(ctx: EngineContext):
    """服务启动时自动恢复：env AGENTLY_MAIL_ENABLED=true 且有持久化配置。"""
    if os.getenv("AGENTLY_MAIL_ENABLED", "").lower() != "true":
        return None
    bot_key = os.getenv("AGENTLY_MAIL_BOT_KEY", "agently-mail-1")
    store = AgentlyMailStore(_store_path(bot_key))
    cfg = store.get_config()
    if not cfg or not cfg.get("default_recipient"):
        logger.info("[agently-mail-engine] AGENTLY_MAIL_ENABLED=true 但无持久化配置，跳过自动恢复")
        return None
    engine = _build_engine(bot_key, cfg)
    logger.info(f"  [外置引擎] agently-mail 已自动恢复: bot_key={bot_key}, recipient={cfg['default_recipient']}")
    return engine


def _start(ctx: EngineContext, params: Dict[str, Any]):
    """管理台 / 通用 API 动态启动。校验参数 → 持久化 → 返回引擎实例。

    （停旧实例 / 挂回调 / 注册 / start() 由 admin._start_engine 统一编排。）
    """
    default_recipient = _norm_email(str(params.get("default_recipient") or ""))
    if not _EMAIL_RE.match(default_recipient):
        return {"success": False, "error": "default_recipient 必填且需为合法邮箱（审批人地址）"}

    poll_interval = params.get("poll_interval_seconds")
    try:
        poll_interval = max(30, int(poll_interval)) if poll_interval is not None else 60
    except (TypeError, ValueError):
        return {"success": False, "error": "poll_interval_seconds 需为整数（秒，最小 30）"}

    bot_key = str(params.get("bot_key") or "agently-mail-1")
    cfg = {
        "default_recipient": default_recipient,
        "allowed_senders": _normalize_senders(params.get("allowed_senders"), default_recipient),
        "poll_interval_seconds": poll_interval,
        "cli_path": str(params.get("cli_path") or "agently-cli"),
    }

    engine = _build_engine(bot_key, {**cfg, "store_path": params.get("store_path")})
    engine._store.set_config({**cfg, "bot_key": bot_key})
    return engine


descriptor = EngineDescriptor(
    name=WORKER_TYPE,
    title="Agently Mail（QQ 邮箱确认）",
    build_startup=_build_startup,
    start=_start,
    credentials=["default_recipient", "allowed_senders", "poll_interval_seconds", "bot_key"],
)
