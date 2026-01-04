"""
DevCloud Worker 配置
"""
import uuid
from pydantic_settings import BaseSettings
from pydantic import Field


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
        default="ws://localhost:8081/ws",
        alias="HIL_URL",
        description="HIL Server 的 WebSocket 地址"
    )
    
    hil_token: str = Field(
        default="",
        alias="HIL_TOKEN",
        description="连接 HIL Server 的鉴权 Token"
    )
    
    # 飞鸽传书配置
    bot_key: str = Field(
        default="",
        alias="BOT_KEY",
        description="企业微信机器人的 Webhook Key"
    )
    
    # 回调服务配置
    callback_port: int = Field(
        default=8082,
        alias="CALLBACK_PORT",
        description="回调服务监听端口"
    )
    
    callback_auth_key: str = Field(
        default="",
        alias="CALLBACK_AUTH_KEY",
        description="回调服务的鉴权 Key"
    )
    
    callback_auth_value: str = Field(
        default="",
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
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


# 全局配置实例
config = WorkerConfig()
