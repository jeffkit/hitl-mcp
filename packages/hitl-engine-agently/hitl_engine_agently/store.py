"""引擎本地状态持久化（JSON，原子写）。

保存两类数据，按 bot_key 分文件，避免同机多实例互相踩：
- ``config``：动态启动参数（default_recipient / allowed_senders / ...），
  服务重启时 ``build_startup`` 据此自动恢复；
- ``seen_message_ids``：已处理过的收件 message_id（防重复回灌），
  以及 ``baseline_done``（引擎首次轮询只建档不触发，之后只看增量）。
"""
from __future__ import annotations

import json
import os
import threading
from typing import Optional

DEFAULT_STORE_DIR = os.path.join(os.path.expanduser("~"), ".hil-mcp")

_SEEN_CAP = 1000


class AgentlyMailStore:
    """线程安全 JSON 存储（引擎跑在 asyncio 单循环里，锁仅防误用）。"""

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self._data: dict = self._load()

    # ── 基础读写 ────────────────────────────────────────────────────────────

    def _load(self) -> dict:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        return {}

    def _save(self) -> None:
        d = os.path.dirname(self.path)
        if d:
            os.makedirs(d, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    # ── 配置 ────────────────────────────────────────────────────────────────

    def get_config(self) -> Optional[dict]:
        with self._lock:
            cfg = self._data.get("config")
            return dict(cfg) if isinstance(cfg, dict) else None

    def set_config(self, config: dict) -> None:
        with self._lock:
            self._data["config"] = dict(config)
            self._save()

    # ── 已见消息（防重） ─────────────────────────────────────────────────────

    def get_seen(self) -> set:
        with self._lock:
            return set(self._data.get("seen_message_ids") or [])

    def add_seen(self, message_ids: list[str]) -> None:
        with self._lock:
            seen: list = self._data.setdefault("seen_message_ids", [])
            for mid in message_ids:
                if mid not in seen:
                    seen.append(mid)
            if len(seen) > _SEEN_CAP:
                del seen[: len(seen) - _SEEN_CAP]
            self._save()

    # ── 基线标记 ────────────────────────────────────────────────────────────

    def is_baseline_done(self) -> bool:
        with self._lock:
            return bool(self._data.get("baseline_done"))

    def mark_baseline_done(self) -> None:
        with self._lock:
            self._data["baseline_done"] = True
            self._save()
