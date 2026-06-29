"""iLink Worker 配置。

支持从 JSON 配置文件加载（优先）和环境变量加载。
凭证（bot_token、get_updates_buf、context_tokens）独立存放在 token_store 文件，
与本配置分离——配置描述"怎么连"，token_store 描述"登录态"。
"""
import os
import json
import uuid
import logging
from pydantic_settings import BaseSettings
from pydantic import Field

logger = logging.getLogger(__name__)


def _get_config_file_path() -> str:
    if os.getenv("WORKER_CONFIG_FILE"):
        return os.getenv("WORKER_CONFIG_FILE")
    return os.path.join(os.path.dirname(__file__), "..", "worker_config.json")


def _load_json_config() -> dict:
    config_file = _get_config_file_path()
    if os.path.exists(config_file):
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.info(f"从 {config_file} 加载 iLink Worker 配置")
            return data
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
    return {}


_json_config = _load_json_config()


class ILinkWorkerConfig(BaseSettings):
    """iLink Worker 配置"""

    # Worker 标识
    worker_id: str = Field(
        default_factory=lambda: f"ilink-{uuid.uuid4().hex[:8]}",
        alias="WORKER_ID",
        description="Worker 唯一标识",
    )

    # 注册到 HIL Server 时声明的类型与 bot_key（用于 Server 路由）
    worker_type: str = Field(default="ilink", description="Worker 类型，固定 ilink")
    bot_key: str = Field(
        default=_json_config.get("bot_key", "ilink-bot-1"),
        alias="BOT_KEY",
        description="注册到 HIL Server 的 bot_key，MCP 端发送时按此路由",
    )

    # HIL Server 连接配置
    hil_url: str = Field(
        default=_json_config.get("hil_url", "ws://localhost:8081/ws"),
        alias="HIL_URL",
        description="HIL Server 的 WebSocket 地址",
    )
    hil_token: str = Field(
        default=_json_config.get("hil_token", ""),
        alias="HIL_TOKEN",
        description="连接 HIL Server 的鉴权 Token",
    )

    # iLink 上游配置
    ilink_base_url: str = Field(
        default=_json_config.get("ilink_base_url", "https://ilinkai.weixin.qq.com"),
        alias="ILINK_BASE_URL",
        description="iLink API 基础地址",
    )
    token_store_path: str = Field(
        default=_json_config.get("token_store_path", "./data/ilink_store.json"),
        alias="TOKEN_STORE_PATH",
        description="bot_token / get_updates_buf / context_tokens 持久化路径",
    )
    poll_timeout: int = Field(
        default=_json_config.get("poll_timeout", 40),
        alias="ILINK_POLL_TIMEOUT",
        description="iLink getupdates 长轮询超时（秒）",
    )

    # 重连配置（WS 断开后）
    reconnect_delay: float = Field(default=5.0, description="WS 重连延迟（秒）")
    max_reconnect_delay: float = Field(default=60.0, description="最大 WS 重连延迟（秒）")

    # 心跳配置
    heartbeat_interval: int = Field(default=20, description="心跳间隔（秒）")
    heartbeat_timeout: int = Field(default=60, description="心跳超时（秒）")

    config_file: str = Field(default=_get_config_file_path(), description="配置文件路径")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


config = ILinkWorkerConfig()
