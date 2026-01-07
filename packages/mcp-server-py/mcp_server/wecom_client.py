"""
服务客户端

用于 MCP Server 调用 HIL Server
"""
import base64
import logging
from pathlib import Path
from typing import Any

import httpx

from .config import config

logger = logging.getLogger(__name__)


class WeComClient:
    """企业微信客户端（连接 HIL Server）"""
    
    def __init__(self, base_url: str | None = None):
        # 注意：不在初始化时缓存 base_url，而是每次调用时从 config 读取
        # 这样可以支持命令行参数覆盖配置
        self._base_url_override = base_url
        self.timeout = httpx.Timeout(30.0, connect=10.0)
    
    @property
    def base_url(self) -> str:
        """每次调用时从 config 读取，支持命令行参数覆盖"""
        return (self._base_url_override or config.service_url).rstrip("/")
    
    async def send_message(
        self,
        message: str,
        chat_id: str | None = None,
        user_id: str | None = None,
        chat_type: str = "group",
        images: list[str] | None = None,
        mention_list: list[str] | None = None,
        project_name: str | None = None,
        timeout: int | None = None,
        wait_reply: bool = True,
    ) -> dict:
        """
        发送消息
        
        Args:
            message: 消息内容
            chat_id: 群 ID 或 个人会话 ID
            user_id: 私聊用户 ID
            chat_type: 会话类型 (group/single)
            images: 图片 URL 列表
            mention_list: @的用户列表
            project_name: 项目名称，用于标识消息来源
            timeout: 会话超时时间（秒），传给服务端以保持两边一致
            wait_reply: 是否等待回复（False 则不创建会话）
        
        Returns:
            包含 session_id 的响应
        """
        url = f"{self.base_url}/send"
        
        payload = {
            "message": message,
            "chat_type": chat_type,
            "wait_reply": wait_reply,
        }
        
        if chat_id:
            payload["chat_id"] = chat_id
        if user_id:
            payload["user_id"] = user_id
        if images:
            payload["images"] = images
        if mention_list:
            payload["mention_list"] = mention_list
        if project_name:
            payload["project_name"] = project_name
        if timeout is not None:
            payload["timeout"] = timeout
        
        logger.info(f"发送消息: url={url}, payload={payload}")
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            return response.json()
    
    async def upload_image(self, image_path: str | Path) -> dict:
        """
        上传图片
        
        Args:
            image_path: 本地图片路径
        
        Returns:
            包含 image_url 的响应
        """
        url = f"{self.base_url}/upload-image"
        
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"图片文件不存在: {image_path}")
        
        # 读取图片内容
        content = path.read_bytes()
        
        # 确定 MIME 类型
        suffix = path.suffix.lower()
        mime_types = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }
        content_type = mime_types.get(suffix, "image/png")
        
        logger.info(f"上传图片: url={url}, path={image_path}, size={len(content)}")
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            files = {"file": (path.name, content, content_type)}
            response = await client.post(url, files=files)
            response.raise_for_status()
            return response.json()
    
    async def poll_replies(self, session_id: str) -> dict:
        """
        轮询获取会话回复
        
        Args:
            session_id: 会话 ID
        
        Returns:
            会话状态和回复
        """
        url = f"{self.base_url}/poll/{session_id}"
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url)
            if response.status_code == 404:
                return {"status": "not_found", "has_reply": False, "replies": []}
            response.raise_for_status()
            return response.json()
    
    async def mark_timeout(self, session_id: str) -> dict:
        """
        标记会话超时
        
        Args:
            session_id: 会话 ID
        """
        url = f"{self.base_url}/session/{session_id}/timeout"
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url)
            if response.status_code == 404:
                return {"success": False, "message": "会话不存在"}
            response.raise_for_status()
            return response.json()


# 全局客户端实例
client = WeComClient()
