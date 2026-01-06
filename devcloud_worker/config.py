"""
DevCloud Worker 配置

支持从 JSON 配置文件加载（优先）和环境变量加载
"""
import os
import json
import uuid
import logging
from pydantic_settings import BaseSettings
from pydantic import Field

logger = logging.getLogger(__name__)


def _get_config_file_path() -> str:
    """获取配置文件路径"""
    if os.getenv("WORKER_CONFIG_FILE"):
        return os.getenv("WORKER_CONFIG_FILE")
    # 默认在项目根目录
    return os.path.join(os.path.dirname(__file__), "..", "worker_config.json")


def _load_json_config() -> dict:
    """从 JSON 配置文件加载配置"""
    config_file = _get_config_file_path()
    
    if os.path.exists(config_file):
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.info(f"从 {config_file} 加载 Worker 配置")
            return data
        except Exception as e:
            logger.error(f"加载 Worker 配置文件失败: {e}")
    
    return {}


# 预加载 JSON 配置
_json_config = _load_json_config()


class WorkerConfig(BaseSettings):
    """DevCloud Worker 配置"""
    
    # Worker 标识
    worker_id: str = Field(
        default_factory=lambda: f"worker-{uuid.uuid4().hex[:8]}",
        alias="WORKER_ID",
        description="Worker 唯一标识"
    )
    
    # HIL Server 连接配置
    hil_url: str = Field(
        default=_json_config.get("hil_url", "ws://localhost:8081/ws"),
        alias="HIL_URL",
        description="HIL Server 的 WebSocket 地址"
    )
    
    hil_token: str = Field(
        default=_json_config.get("hil_token", ""),
        alias="HIL_TOKEN",
        description="连接 HIL Server 的鉴权 Token"
    )
    
    # 飞鸽传书配置
    bot_key: str = Field(
        default=_json_config.get("bot_key", ""),
        alias="BOT_KEY",
        description="企业微信机器人的 Webhook Key"
    )
    
    # 回调服务配置
    callback_port: int = Field(
        default=_json_config.get("callback_port", 8082),
        alias="CALLBACK_PORT",
        description="回调服务监听端口"
    )
    
    callback_auth_key: str = Field(
        default=_json_config.get("callback_auth_key", ""),
        alias="CALLBACK_AUTH_KEY",
        description="回调服务的鉴权 Key"
    )
    
    callback_auth_value: str = Field(
        default=_json_config.get("callback_auth_value", ""),
        alias="CALLBACK_AUTH_VALUE",
        description="回调服务的鉴权 Value"
    )
    
    # 重连配置
    reconnect_delay: float = Field(
        default=5.0,
        description="重连延迟（秒）"
    )
    
    max_reconnect_delay: float = Field(
        default=60.0,
        description="最大重连延迟（秒）"
    )
    
    # 心跳配置
    heartbeat_interval: int = Field(
        default=20,
        description="心跳间隔（秒）"
    )
    
    heartbeat_timeout: int = Field(
        default=60,
        description="心跳超时时间（秒），应大于 heartbeat_interval * 2"
    )
    
    # 配置文件路径（用于保存配置）
    config_file: str = Field(
        default=_get_config_file_path(),
        description="配置文件路径"
    )
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"
    
    def save_config(self) -> dict:
        """保存配置到 JSON 文件"""
        try:
            data = {
                "bot_key": self.bot_key,
                "hil_url": self.hil_url,
                "callback_port": self.callback_port,
                "description": "HIL Worker - 接收用户回复"
            }
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"Worker 配置已保存到 {self.config_file}")
            return {"success": True, "message": "配置已保存"}
        except Exception as e:
            logger.error(f"保存 Worker 配置失败: {e}")
            return {"success": False, "error": str(e)}


# 全局配置实例
config = WorkerConfig()
