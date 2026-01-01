"""
MCP Server 配置
"""
import os
from pydantic_settings import BaseSettings
from pydantic import Field


class MCPConfig(BaseSettings):
    """MCP Server 配置"""
    
    # DevCloud 服务地址
    devcloud_service_url: str = Field(
        default="http://localhost:8080",
        description="DevCloud 服务的访问地址"
    )
    
    # 默认 Chat ID（用于发送消息的群或私聊）
    default_chat_id: str = Field(
        default="",
        description="默认发送消息的 Chat ID（群聊或私聊）"
    )
    
    # 默认超时时间（秒）
    default_timeout: int = Field(
        default=1200,  # 20 分钟
        description="默认等待回复超时时间"
    )
    
    # 轮询间隔（秒）
    poll_interval: int = Field(
        default=2,
        description="轮询获取回复的间隔"
    )
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


# 全局配置实例
config = MCPConfig()
