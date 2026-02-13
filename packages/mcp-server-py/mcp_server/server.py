"""
Human-in-the-Loop MCP Server

让 AI 能够发送消息到企业微信并等待用户回复

运行方式:
    python -m mcp_server.server --service-url http://hitl.woa.com/api --chat-id xxx --project-name xxx
"""
import argparse
import asyncio
import base64
import json
import logging
import mimetypes
import time
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import ImageContent, TextContent
from pydantic import Field

from .config import config
from .wecom_client import WeComClient

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# 创建 MCP 实例
mcp = FastMCP(
    "hitl-mcp",
    instructions="企业微信 Human-in-the-Loop MCP - 发送消息并等待用户回复"
)

# 创建客户端
client = WeComClient()


async def download_image(url: str) -> tuple[str, str] | None:
    """
    下载图片并返回 (base64_data, mime_type)。
    
    支持:
    - data: URL (直接提取 base64)
    - http/https URL (下载并编码)
    
    Returns:
        (base64_data, mime_type) 或 None（下载失败时）
    """
    try:
        parsed = urlparse(url)
        
        # 处理 data URL: data:image/jpeg;base64,xxxxx
        if parsed.scheme == "data":
            # 格式: data:[<mediatype>][;base64],<data>
            header, _, data = url.partition(",")
            if not data:
                logger.warning(f"无效的 data URL: {url[:100]}")
                return None
            # 提取 mime type: "data:image/jpeg;base64" -> "image/jpeg"
            mime_type = header.split(":")[1].split(";")[0] if ":" in header else "image/png"
            return data, mime_type
        
        # 处理 HTTP(S) URL
        if parsed.scheme in ("http", "https"):
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as http_client:
                response = await http_client.get(url)
                response.raise_for_status()
                
                # 从 Content-Type 获取 mime type
                content_type = response.headers.get("content-type", "")
                mime_type = content_type.split(";")[0].strip()
                
                # 如果 Content-Type 不是图片类型，尝试从 URL 推断
                if not mime_type.startswith("image/"):
                    guessed, _ = mimetypes.guess_type(parsed.path)
                    mime_type = guessed or "image/png"
                
                # 编码为 base64
                b64_data = base64.b64encode(response.content).decode("utf-8")
                logger.info(f"图片下载成功: {url[:80]}..., size={len(response.content)}, type={mime_type}")
                return b64_data, mime_type
        
        logger.warning(f"不支持的图片 URL scheme: {parsed.scheme}")
        return None
        
    except Exception as e:
        logger.warning(f"下载图片失败: {url[:80]}..., error={e}")
        return None


async def process_replies_with_images(result: dict) -> list | dict:
    """
    处理回复中的图片：下载图片并转换为 MCP ImageContent。
    
    如果回复包含图片，返回 [TextContent, ImageContent, ...] 列表。
    如果没有图片，返回原始 dict（保持向后兼容）。
    """
    replies = result.get("replies", [])
    image_contents: list[ImageContent] = []
    
    for reply in replies:
        image_url = reply.get("image_url")
        if not image_url:
            continue
        
        downloaded = await download_image(image_url)
        if downloaded:
            b64_data, mime_type = downloaded
            image_contents.append(
                ImageContent(type="image", data=b64_data, mimeType=mime_type)
            )
            logger.info(f"图片已编码为 MCP ImageContent: mime={mime_type}")
    
    if not image_contents:
        return result
    
    # 有图片时，返回 [TextContent(JSON), ImageContent, ...] 列表
    # 文本部分仍包含完整的回复信息（含 image_url），确保向后兼容
    content: list[TextContent | ImageContent] = [
        TextContent(type="text", text=json.dumps(result, ensure_ascii=False))
    ]
    content.extend(image_contents)
    
    logger.info(f"返回 MCP 响应: {len(content)} 个内容块 (1 text + {len(image_contents)} images)")
    return content


@mcp.tool()
async def send_and_wait_reply(
    message: Annotated[str, Field(description="要发送给用户的消息内容")],
    chat_id: Annotated[str | None, Field(description="目标群 ID 或个人会话 ID。如果不指定，使用默认配置")] = None,
    image_paths: Annotated[list[str] | None, Field(description="要发送的本地图片文件路径列表")] = None,
    project_name: Annotated[str | None, Field(description="项目名称，用于标识消息来源。如果不指定，使用默认配置")] = None,
) -> dict | list:
    """
    发送消息到企业微信并等待用户回复。
    
    这个工具会：
    1. 将消息发送到指定的企微群或个人会话
    2. 如果提供了图片路径，也会上传并发送图片
    3. 等待用户回复（需要用户在企微中 @机器人 回复）
    4. 返回用户的回复内容（如果回复包含图片，会自动下载并作为图片内容返回）
    
    注意：
    - 用户需要 @机器人 才能触发回调
    - 超时后会返回超时状态
    - 私聊场景下用户直接回复即可
    - 当多个项目同时发送消息时，用户可以使用「引用回复」来精确回复特定消息
    - 用户回复中包含的图片会被自动下载并嵌入到响应中，AI 可以直接看到图片内容
    
    返回格式：
    - 纯文本回复: {"status": "success", "replies": [...], "message": "..."}
    - 含图片回复: [TextContent(JSON), ImageContent(图片1), ImageContent(图片2), ...]
    """
    # 使用配置中的超时时间（由 MCP 统一管理，不受 AI 控制）
    timeout = config.default_timeout
    
    try:
        # 如果没有指定 chat_id，使用配置中的默认值
        logger.info(f"原始 chat_id={chat_id}, config.default_chat_id={config.default_chat_id}")
        effective_chat_id = chat_id or config.default_chat_id or None
        logger.info(f"开始发送消息: message={message[:50]}..., effective_chat_id={effective_chat_id}, timeout={timeout}, project_name={project_name}")
        
        # 处理图片上传
        image_urls = []
        if image_paths:
            for path in image_paths:
                if Path(path).exists():
                    logger.info(f"上传图片: {path}")
                    result = await client.upload_image(path)
                    if result.get("success") and result.get("image_url"):
                        image_urls.append(result["image_url"])
                        logger.info(f"图片上传成功: {path}")
                    else:
                        logger.warning(f"图片上传失败: {path}, {result}")
                else:
                    logger.warning(f"图片文件不存在: {path}")
        
        logger.info(f"共上传 {len(image_urls)} 张图片")
        
        # 发送消息（把 timeout 传给服务端，确保会话超时时间一致）
        send_result = await client.send_message(
            message=message,
            chat_id=effective_chat_id,
            images=image_urls if image_urls else None,
            project_name=project_name,
            timeout=timeout,
        )
        
        if not send_result.get("success"):
            return {
                "status": "error",
                "replies": [],
                "message": f"发送消息失败: {send_result.get('error', '未知错误')}"
            }
        
        session_id = send_result.get("session_id")
        if not session_id:
            return {
                "status": "error",
                "replies": [],
                "message": "发送成功但未获取到会话 ID"
            }
        
        logger.info(f"消息发送成功, session_id={session_id}, 开始等待回复...")
        
        # 轮询等待回复
        start_time = time.time()
        poll_interval = config.poll_interval
        
        try:
            while time.time() - start_time < timeout:
                try:
                    result = await client.poll_replies(session_id)
                    
                    if result.get("has_reply"):
                        replies = result.get("replies", [])
                        logger.info(f"收到用户回复: {len(replies)} 条")
                        reply_result = {
                            "status": "success",
                            "replies": replies,
                            "message": f"收到 {len(replies)} 条回复"
                        }
                        # 自动下载图片并作为 MCP ImageContent 返回
                        return await process_replies_with_images(reply_result)
                    
                    if result.get("status") == "not_found":
                        return {
                            "status": "error",
                            "replies": [],
                            "message": "会话不存在或已过期"
                        }
                    
                except Exception as e:
                    logger.warning(f"轮询失败: {e}")
                
                # 等待一段时间再轮询
                await asyncio.sleep(poll_interval)
            
            # 超时
            logger.info(f"等待超时: session_id={session_id}")
            
            # 标记会话超时
            await client.mark_timeout(session_id)
            
            return {
                "status": "timeout",
                "replies": [],
                "message": f"等待 {timeout} 秒后超时，未收到用户回复"
            }
        
        except asyncio.CancelledError:
            # 用户取消了 MCP 调用，通知服务端清理会话
            logger.info(f"用户取消了等待: session_id={session_id}")
            try:
                await client.mark_timeout(session_id)
                logger.info(f"已通知服务端清理会话: session_id={session_id}")
            except Exception as e:
                logger.warning(f"通知服务端清理会话失败: {e}")
            # 重新抛出 CancelledError，让上层正确处理取消
            raise
        
    except asyncio.CancelledError:
        # 如果在发送消息阶段被取消，直接抛出
        raise
    except Exception as e:
        logger.error(f"发送消息并等待回复失败: {e}", exc_info=True)
        return {
            "status": "error",
            "replies": [],
            "message": f"发生错误: {str(e)}"
        }


@mcp.tool()
async def send_message_only(
    message: Annotated[str, Field(description="要发送给用户的消息内容")],
    chat_id: Annotated[str | None, Field(description="目标群 ID 或个人会话 ID")] = None,
    image_paths: Annotated[list[str] | None, Field(description="要发送的本地图片文件路径列表")] = None,
    project_name: Annotated[str | None, Field(description="项目名称，用于标识消息来源。如果不指定，使用默认配置")] = None,
) -> dict:
    """
    仅发送消息到企业微信，不等待回复。
    
    适用于只需要通知用户、不需要交互的场景。
    
    返回格式：
    {
        "status": "success" | "error",
        "message": "描述信息"
    }
    """
    try:
        # 如果没有指定 chat_id，使用配置中的默认值
        effective_chat_id = chat_id or config.default_chat_id or None
        logger.info(f"发送消息（不等待回复）: message={message[:50]}..., chat_id={effective_chat_id}")
        
        # 处理图片上传
        image_urls = []
        if image_paths:
            for path in image_paths:
                if Path(path).exists():
                    result = await client.upload_image(path)
                    if result.get("success") and result.get("image_url"):
                        image_urls.append(result["image_url"])
        
        # 发送消息（不等待回复，不创建会话）
        send_result = await client.send_message(
            message=message,
            chat_id=effective_chat_id,
            images=image_urls if image_urls else None,
            project_name=project_name,
            wait_reply=False,  # 不创建会话
        )
        
        if send_result.get("success"):
            return {
                "status": "success",
                "message": "消息发送成功"
            }
        else:
            return {
                "status": "error",
                "message": f"发送失败: {send_result.get('error', '未知错误')}"
            }
            
    except Exception as e:
        logger.error(f"发送消息失败: {e}", exc_info=True)
        return {
            "status": "error",
            "message": f"发生错误: {str(e)}"
        }


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description="WeCom HIL MCP Server")
    parser.add_argument(
        "--service-url",
        dest="service_url",
        help="HIL Server 的访问地址（如 http://hitl.woa.com 或 http://hitl.woa.com/api）"
    )
    parser.add_argument(
        "--chat-id",
        dest="chat_id",
        help="默认发送消息的 Chat ID（群聊或私聊）"
    )
    parser.add_argument(
        "--project-name",
        dest="project_name",
        help="默认项目名称，用于标识消息来源"
    )
    parser.add_argument(
        "--timeout",
        dest="timeout",
        type=int,
        help="默认等待回复超时时间（秒），默认 1200 秒（20 分钟）"
    )
    return parser.parse_args()


def main():
    """主函数"""
    args = parse_args()
    
    # 命令行参数覆盖配置（优先级：命令行 > 环境变量 > 默认值）
    if args.service_url:
        config.service_url = args.service_url
    if args.chat_id:
        config.default_chat_id = args.chat_id
    if args.project_name:
        config.default_project_name = args.project_name
    if args.timeout:
        config.default_timeout = args.timeout
    
    logger.info(f"启动 WeCom HIL MCP Server...")
    logger.info(f"  服务地址: {config.service_url}")
    logger.info(f"  默认 Chat ID: {config.default_chat_id or '(未设置)'}")
    logger.info(f"  默认项目名: {config.default_project_name or '(未设置)'}")
    logger.info(f"  超时时间: {config.default_timeout}s")
    logger.info(f"  轮询间隔: {config.poll_interval}s")
    
    mcp.run()


if __name__ == "__main__":
    main()
