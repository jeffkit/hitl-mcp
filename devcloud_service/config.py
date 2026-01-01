"""
DevCloud 服务配置
"""
import os
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field


class DevCloudConfig(BaseSettings):
    """DevCloud 服务配置"""
    
    # 服务监听端口
    port: int = Field(
        default=8080,
        alias="DEVCLOUD_PORT",
        description="服务监听端口"
    )
    
    # 飞鸽传书配置
    bot_key: str = Field(
        default="",
        description="机器人的 Webhook Key（必填）"
    )
    
    # 回调鉴权配置（可选，用于验证飞鸽回调的身份）
    callback_auth_key: str = Field(
        default="",
        description="回调服务的鉴权 Key"
    )
    
    callback_auth_value: str = Field(
        default="",
        description="回调服务的鉴权 Value"
    )
    
    # 存储配置
    data_dir: Path = Field(
        default=Path("./data"),
        description="会话数据存储目录"
    )
    
    session_expire_seconds: int = Field(
        default=3600,
        description="会话过期时间（秒）"
    )
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"
    
    def ensure_data_dir(self) -> Path:
        """确保数据目录存在"""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir


# 全局配置实例
config = DevCloudConfig()
