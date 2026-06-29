"""
HITL Server 配置
"""
from pydantic_settings import BaseSettings
from pydantic import Field


class HITLConfig(BaseSettings):
    """HITL Server 配置"""
    
    # 服务监听配置
    host: str = Field(
        default="127.0.0.1",
        description="服务监听地址（本地服务，默认仅本机访问）"
    )
    port: int = Field(
        default=8081,
        alias="HITL_PORT",
        description="服务监听端口"
    )
    
    # ========== 运行模式 ==========
    # relay: 通过 WebSocket 转发给 Worker（公网模式）
    # direct: 直接调用 fly-pigeon（内网模式）
    # auto: 自动检测（有 bot_key 则 direct，否则 relay）
    mode: str = Field(
        default="auto",
        alias="HITL_MODE",
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
        alias="HITL_WORKER_TOKEN",
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
    
    # ========== 消息分拆配置 ==========
    max_message_bytes: int = Field(
        default=2048,
        alias="MAX_MESSAGE_BYTES",
        description="单条消息最大字节数（建议2048，企微后端可能在此限制分拆）"
    )
    
    # ========== 内置引擎（in-process，无需独立 Worker 进程）==========
    enable_ilink_engine: bool = Field(
        default=False,
        alias="ENABLE_ILINK_ENGINE",
        description="启用 iLink 内置引擎（进程内维持长轮询，无需 ilink-worker）",
    )
    ilink_bot_key: str = Field(
        default="ilink-bot-1",
        alias="ILINK_BOT_KEY",
        description="iLink 内置引擎的 bot_key（MCP 端按此路由）",
    )
    ilink_base_url: str = Field(
        default="https://ilinkai.weixin.qq.com",
        alias="ILINK_BASE_URL",
        description="iLink API 基础地址",
    )
    ilink_token_store_path: str = Field(
        default="",
        alias="ILINK_TOKEN_STORE_PATH",
        description="iLink 凭证存储路径（默认 ~/.hil-mcp/ilink_store.json）",
    )
    ilink_poll_timeout: int = Field(
        default=40,
        alias="ILINK_POLL_TIMEOUT",
        description="iLink getupdates 长轮询超时（秒）",
    )

    # ========== 内置引擎：企业微信 AI Bot ==========
    enable_wecom_aibot_engine: bool = Field(
        default=False,
        alias="ENABLE_WECOM_AIBOT_ENGINE",
        description="启用企微 AI Bot 内置引擎（进程内维持 WS 长连接）",
    )
    wecom_aibot_bot_key: str = Field(
        default="wecom-aibot-1",
        alias="WECOM_AIBOT_BOT_KEY",
        description="企微 AI Bot 内置引擎的 bot_key（MCP 端按此路由）",
    )
    wecom_aibot_bot_id: str = Field(
        default="",
        alias="WECOM_AIBOT_BOT_ID",
        description="企微 AI Bot ID",
    )
    wecom_aibot_bot_secret: str = Field(
        default="",
        alias="WECOM_AIBOT_BOT_SECRET",
        description="企微 AI Bot Secret",
    )
    wecom_aibot_ws_url: str = Field(
        default="wss://openws.work.weixin.qq.com",
        alias="WECOM_AIBOT_WS_URL",
        description="企微 AI Bot WebSocket 地址",
    )
    wecom_aibot_heartbeat_interval: int = Field(
        default=30,
        alias="WECOM_AIBOT_HEARTBEAT_INTERVAL",
        description="心跳间隔（秒）",
    )
    wecom_aibot_reconnect_delay: int = Field(
        default=5,
        alias="WECOM_AIBOT_RECONNECT_DELAY",
        description="断线重连延迟（秒）",
    )
    wecom_aibot_store_path: str = Field(
        default="",
        alias="WECOM_AIBOT_STORE_PATH",
        description="企微 AI Bot 凭证存储路径（默认 ~/.hil-mcp/wecom_aibot_store.json），重启后据此自动注册",
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
config = HITLConfig()
