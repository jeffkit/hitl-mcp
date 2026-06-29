"""内置引擎管理器（单例）。

- 持有按配置启用的引擎实例，按 worker_type / bot_key 索引
- app.py lifespan 调 start_all/stop_all
- /api/send 与 /api/ilink/* 路由通过它查找内置引擎；命中则进程内调用，
  未命中则回退到 WS 外部 worker（ws_manager）
"""
import logging
from typing import Optional

from .base import BaseEngine

logger = logging.getLogger(__name__)


class EngineManager:
    def __init__(self):
        self._engines: list[BaseEngine] = []
        self._by_bot_key: dict[str, BaseEngine] = {}
        self._by_type: dict[str, list[BaseEngine]] = {}

    def register(self, engine: BaseEngine) -> None:
        self._engines.append(engine)
        if engine.bot_key:
            self._by_bot_key[engine.bot_key] = engine
        self._by_type.setdefault(engine.worker_type, []).append(engine)
        logger.info(f"已注册内置引擎: type={engine.worker_type}, bot_key={engine.bot_key}")

    def get_by_bot_key(self, bot_key: str) -> Optional[BaseEngine]:
        if not bot_key:
            return None
        return self._by_bot_key.get(bot_key)

    def get_by_type(self, worker_type: str) -> Optional[BaseEngine]:
        engines = self._by_type.get(worker_type)
        return engines[0] if engines else None

    def all(self) -> list[BaseEngine]:
        return list(self._engines)

    def status_all(self) -> list[dict]:
        return [e.status() for e in self._engines]

    def remove(self, bot_key: str) -> Optional[BaseEngine]:
        """按 bot_key 移除并返回引擎（不 stop，由调用方负责 stop）。"""
        engine = self._by_bot_key.get(bot_key)
        if not engine:
            return None
        self._engines.remove(engine)
        self._by_bot_key.pop(bot_key, None)
        if engine.worker_type in self._by_type:
            self._by_type[engine.worker_type] = [
                e for e in self._by_type[engine.worker_type] if e is not engine
            ]
        return engine

    async def start_all(self) -> None:
        for engine in self._engines:
            try:
                await engine.start()
            except Exception as e:
                logger.error(f"启动引擎 {engine.worker_type}/{engine.bot_key} 失败: {e}", exc_info=True)

    async def stop_all(self) -> None:
        for engine in self._engines:
            try:
                await engine.stop()
            except Exception as e:
                logger.error(f"停止引擎 {engine.worker_type}/{engine.bot_key} 失败: {e}", exc_info=True)


engine_manager = EngineManager()
