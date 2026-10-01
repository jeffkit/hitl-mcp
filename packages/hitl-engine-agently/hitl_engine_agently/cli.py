"""agently-cli 异步子进程封装。

CLI 的 stdout 为 JSON envelope（``{"ok": bool, "data": ..., "error": {...}}``），
tip 文案走 stderr。退出码语义（见 agently-mail skill）：

- 0 成功；1 服务端/网络抖动；2 参数不合规；3 授权失效；
- 4 本地网络错误；6 业务永久拒绝；7 限频；8 缺少 confirmation-token。

发送为两阶段：第一次调用返回 ``ctk_`` 前缀确认令牌，带
``--confirmation-token`` 重发同一命令即完成发送。本封装自动完成该握手，
使引擎可作为后台服务无人值守发信。
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)


class AgentlyCliError(Exception):
    """agently-cli 非零退出。code 为 CLI 退出码，message 为 envelope 里的原文。

    envelope 为 stdout 解析出的原始 JSON（可能含确认令牌等 data 字段）。
    """

    def __init__(self, code: int, message: str, envelope: Optional[dict] = None):
        super().__init__(f"agently-cli exit={code}: {message}")
        self.code = code
        self.message = message
        self.envelope = envelope or {}


def _find_ctk(obj: Any) -> Optional[str]:
    """在 envelope 里递归找第一个 ctk_ 前缀字符串（确认令牌）。"""
    if isinstance(obj, str):
        return obj if obj.startswith("ctk_") else None
    if isinstance(obj, dict):
        for v in obj.values():
            found = _find_ctk(v)
            if found:
                return found
    if isinstance(obj, list):
        for v in obj:
            found = _find_ctk(v)
            if found:
                return found
    return None


def html_to_text(html: str) -> str:
    """极简 HTML → 纯文本（去 style/script、标签、实体、折叠空白）。"""
    import html as _html
    import re

    text = re.sub(r"(?is)<(style|script|head)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|tr|li|h[1-6]|table)>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = _html.unescape(text)
    text = text.replace("\u00a0", " ")  # &nbsp; 归一为普通空格
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


class AgentlyCli:
    """agently-cli 子进程封装（每调用一个进程，无常驻连接）。"""

    def __init__(self, cli_path: str = "agently-cli", timeout: float = 45.0):
        self.cli_path = cli_path
        self.timeout = timeout

    async def run(self, *args: str) -> dict:
        """执行一条 CLI 命令，返回解析后的 envelope dict。非零退出抛 AgentlyCliError。"""
        argv = [self.cli_path, *args]
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            raise AgentlyCliError(4, f"找不到可执行文件: {self.cli_path}（agently-cli 需在 PATH 上）")
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise AgentlyCliError(4, f"命令超时（>{self.timeout}s）: {' '.join(args)}")

        out = stdout.decode("utf-8", errors="replace").strip()
        err = stderr.decode("utf-8", errors="replace").strip()
        code = proc.returncode or 0
        if code == 0:
            try:
                envelope = json.loads(out)
            except json.JSONDecodeError:
                raise AgentlyCliError(1, f"无法解析 stdout JSON: {out[:200]}")
            if envelope.get("ok") is False:
                msg = (envelope.get("error") or {}).get("message") or out[:200]
                raise AgentlyCliError(1, str(msg))
            return envelope

        message = err or out
        parsed: dict = {}
        try:
            parsed = json.loads(out)
            message = str((parsed.get("error") or {}).get("message") or message)
        except json.JSONDecodeError:
            pass
        raise AgentlyCliError(code, message[:300], envelope=parsed)

    async def me(self) -> dict:
        """当前授权账号与别名（+me 的 data）。"""
        envelope = await self.run("+me")
        return envelope.get("data") or {}

    async def list_inbox(self, limit: int = 20) -> list[dict]:
        """收件箱最近消息元信息列表（含 message_id / subject / from / snippet）。"""
        envelope = await self.run("message", "+list", "--dir", "inbox", "--limit", str(limit))
        data = (envelope.get("data") or {}).get("data")
        return data if isinstance(data, list) else []

    async def read(self, message_id: str) -> dict:
        """读取单封邮件完整内容（含 body / body_format）。"""
        envelope = await self.run("message", "+read", "--id", message_id)
        return envelope.get("data") or {}

    async def send(self, to: Iterable[str], subject: str, body: str) -> dict:
        """发送邮件（自动完成两阶段确认握手），返回最终 envelope 的 data。

        握手实测形状（CLI 1.0.5）：首次调用 exit 0，envelope data 带
        ``confirmation_required: true`` + ``confirmation_token``；带 token
        重发同一命令才真正发出。历史 exit-8 路径保留为兜底。
        """
        to_list = [t for t in (x.strip() for x in to) if t]
        if not to_list:
            raise AgentlyCliError(2, "收件人为空")
        base_args = ["message", "+send"]
        for addr in to_list:
            base_args += ["--to", addr]
        base_args += ["--subject", subject, "--body", body]

        try:
            envelope = await self.run(*base_args)
        except AgentlyCliError as e:
            if e.code != 8:  # 兜底：历史版本以 exit 8 表示需要确认
                raise
            envelope = e.envelope
        data = envelope.get("data") or {}
        token = (
            data.get("confirmation_token")
            if data.get("confirmation_required")
            else None
        ) or _find_ctk(data)
        if not token:
            raise AgentlyCliError(8, "需要确认但响应中未找到确认令牌", envelope=envelope)

        # 带 token 重发同一命令，完成发送
        envelope = await self.run(*base_args, "--confirmation-token", token)
        return envelope.get("data") or {}
