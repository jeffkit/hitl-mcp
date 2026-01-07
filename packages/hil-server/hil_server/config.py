"""
HIL Server 配置
"""
from pydantic_settings import BaseSettings
from pydantic import Field


class HILConfig(BaseSettings):
    """HIL Server 配置"""
    
    # 服务监听配置
    host: str = Field(
        default="0.0.0.0",
        description="服务监听地址"
    )
    port: int = Field(
        default=8081,
        alias="HIL_PORT",
        description="服务监听端口"
    )
    
    # ========== 运行模式 ==========
    # relay: 通过 WebSocket 转发给 Worker（公网模式）
    # direct: 直接调用 fly-pigeon（内网模式）
    # auto: 自动检测（有 bot_key 则 direct，否则 relay）
    mode: str = Field(
        default="auto",
        alias="HIL_MODE",
        description="运行模式: relay/direct/auto"
    )
    
    # ========== Direct 模式配置（直接调用 fly-pigeon）==========
    bot_key: str = Field(
        default="",
        alias="BOT_KEY",
        description="fly-pigeon 机器人 Key（direct 模式必填）"
    )
    
    # ========== Relay 模式配置（通过 Worker）==========
    worker_token: str = Field(
        default="",
        alias="HIL_WORKER_TOKEN",
        description="Worker 连接的鉴权 Token"
    )
    
    # 请求超时配置
    request_timeout: int = Field(
        default=30,
        description="请求超时时间（秒）"
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
    
    # ========== Forward Service 配置（用于统一管理台）==========
    forward_service_url: str = Field(
        default="",
        alias="FORWARD_SERVICE_URL",
        description="Forward Service 地址（如 http://localhost:8083）"
    )
    
    # ========== 管理台认证配置 ==========
    admin_username: str = Field(
        default="admin",
        alias="ADMIN_USERNAME",
        description="管理台登录用户名"
    )
    admin_password: str = Field(
        default="jarvis2026",
        alias="ADMIN_PASSWORD",
        description="管理台登录密码"
    )
    admin_token_secret: str = Field(
        default="hil-mcp-secret-key-2026",
        alias="ADMIN_TOKEN_SECRET",
        description="JWT Token 密钥"
    )
    
    @property
    def effective_mode(self) -> str:
        """获取实际运行模式"""
        if self.mode == "auto":
            # 有 bot_key 则使用 direct 模式
            return "direct" if self.bot_key else "relay"
        return self.mode
    
    @property
    def is_direct_mode(self) -> bool:
        """是否为直连模式"""
        return self.effective_mode == "direct"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


# 全局配置实例
config = HILConfig()
