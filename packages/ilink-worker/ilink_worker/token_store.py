"""iLink Token 持久化存储（JSON 文件）。

存储内容：
  bot_token        — ClawBot 登录凭证
  get_updates_buf  — 长轮询游标
  context_tokens   — { from_user_id: context_token }（回复时必须携带）
"""
import os
import json
import logging
import threading

logger = logging.getLogger(__name__)


class TokenStore:
    """线程安全的 iLink token 存储。"""

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

    # ── bot_token ──────────────────────────────────────────────
    def get_bot_token(self) -> str | None:
        with self._lock:
            return self._data.get("bot_token")

    def set_bot_token(self, token: str) -> None:
        with self._lock:
            self._data["bot_token"] = token
            self._save()

    # ── get_updates_buf ────────────────────────────────────────
    def get_updates_buf(self) -> str:
        with self._lock:
            return self._data.get("get_updates_buf", "")

    def set_updates_buf(self, buf: str) -> None:
        with self._lock:
            self._data["get_updates_buf"] = buf
            self._save()

    # ── context_tokens ─────────────────────────────────────────
    def get_context_token(self, from_user_id: str) -> str | None:
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

    def resolve_recipient(self) -> str | None:
        """返回第一个已激活用户 ID（通常就是自己）。"""
        with self._lock:
            users = list((self._data.get("context_tokens") or {}).keys())
            return users[0] if users else None
